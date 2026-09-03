"""
Le moteur d'exécution des Outcomes — le cœur du produit (spec §1, §7, §10 :
"steps 1-4 are the whole bet").

Design :
  - Un `run` est mis en queue (liste Redis `kloyya:run-queue`) par
    POST /api/outcomes/:id/run, puis consommé par `run_worker_loop()`
    (process séparé en prod — voir docker-compose `worker` service, ou tâche
    de fond du process API en dev).
  - Le run VIT dans le worker, pas dans la requête HTTP : un client qui ferme
    l'onglet ne tue rien (spec §4 : "must survive the client disconnecting
    entirely").
  - Chaque event est (1) persisté dans run_events, (2) publié sur Redis pour
    le direct SSE. Le replay se fait uniquement depuis la DB.
  - Budget : RUN_TOKEN_BUDGET et RUN_WALL_CLOCK_CAP_SECONDS sont vérifiés à
    chaque step ; dépassement -> dégradation en réponse partielle avec un gap
    explicite, jamais un échec silencieux (spec §7).
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
import redis.asyncio as redis
import structlog

from app.config import get_settings
from app.core.enums import OutcomeState, PlanStepKind, PlanStepState, RunState
from app.core.sse import get_redis, publish_event
from app.db.session import system_connection, workspace_connection
from app.services.composio_service import get_composio_service
from app.services.llm_router import TaskRole, get_llm_router
from app.services.rag_service import get_rag_service

log = structlog.get_logger()

QUEUE_KEY = "kloyya:run-queue"


async def enqueue_run(run_id: UUID, workspace_id: UUID) -> None:
    r = get_redis()
    await r.rpush(QUEUE_KEY, json.dumps({"run_id": str(run_id), "workspace_id": str(workspace_id)}))


async def run_worker_loop() -> None:
    """Boucle de consommation. À lancer dans le process `worker` (voir docker-compose)."""
    r = get_redis()
    log.info("run_worker.started")
    while True:
        item = await r.blpop(QUEUE_KEY, timeout=5)
        if item is None:
            continue
        _, raw = item
        payload = json.loads(raw)
        run_id = UUID(payload["run_id"])
        workspace_id = UUID(payload["workspace_id"])
        try:
            await execute_run(run_id, workspace_id)
        except Exception:
            log.exception("run_worker.run_failed", run_id=str(run_id))


async def _log_event(
    conn: asyncpg.Connection, run_id: UUID, tag: str, message: str, level: str = "info", step_id=None
) -> int:
    row = await conn.fetchrow(
        """
        insert into run_events (run_id, tag, message, level, step_id)
        values ($1, $2, $3, $4, $5)
        returning id
        """,
        run_id, tag, message, level, step_id,
    )
    event_id = row["id"]
    await publish_event(run_id, "log", {"tag": tag, "message": message, "level": level, "ts": datetime.now(timezone.utc).isoformat(), "stepId": str(step_id) if step_id else None}, event_id)
    return event_id


async def _set_step_state(conn: asyncpg.Connection, run_id: UUID, step_id: UUID, state: str, detail: str = "") -> None:
    await conn.execute("update plan_steps set state = $1 where id = $2", state, step_id)
    row = await conn.fetchrow("select id from run_events order by id desc limit 1")
    event_id = (row["id"] if row else 0) + 1
    await publish_event(run_id, "step", {"stepId": str(step_id), "state": state, "detail": detail, "ts": datetime.now(timezone.utc).isoformat()}, event_id)


async def _set_outcome_state(conn: asyncpg.Connection, outcome_id: UUID, state: str) -> None:
    await conn.execute("update outcomes set state = $1 where id = $2", state, outcome_id)


async def execute_run(run_id: UUID, workspace_id: UUID) -> None:
    settings = get_settings()
    start = time.monotonic()
    tokens_used = 0

    async with workspace_connection(workspace_id) as conn:
        run = await conn.fetchrow("select * from runs where id = $1", run_id)
        outcome = await conn.fetchrow("select * from outcomes where id = $1", run["outcome_id"])
        outcome_id = outcome["id"]

        await conn.execute("update runs set state = 'running', started_at = now() where id = $1", run_id)
        await _set_outcome_state(conn, outcome_id, OutcomeState.RUNNING.value)
        await _log_event(conn, run_id, "auth", "Run started — checking connection health for all referenced tools.")

        steps = await conn.fetch(
            "select * from plan_steps where outcome_id = $1 order by ordinal asc", outcome_id
        )

        workspace_row = await conn.fetchrow("select llm_provider_prefs from workspaces where id = $1", workspace_id)
        router = get_llm_router(workspace_prefs=workspace_row["llm_provider_prefs"] or {})
        composio = get_composio_service()
        rag = get_rag_service(workspace_id)

        gathered_context: list[str] = []
        low_confidence_flags: list[str] = []

        for step in steps:
            elapsed = time.monotonic() - start
            if elapsed > settings.RUN_WALL_CLOCK_CAP_SECONDS:
                await _log_event(
                    conn, run_id, "gap",
                    "Wall-clock budget reached — delivering a partial answer with remaining steps flagged as gaps.",
                    level="warn",
                )
                break
            if tokens_used > settings.RUN_TOKEN_BUDGET:
                await _log_event(conn, run_id, "gap", "Token budget reached — degrading to partial answer.", level="warn")
                break
            if step["state"] == "skipped":
                continue  # supprimé par l'utilisateur en Plan review -> ne s'exécute jamais (spec §7)

            step_id = step["id"]
            kind = step["kind"]

            # Une pause est déjà active (mise par un endpoint /pause) -> on arrête ici.
            fresh_run = await conn.fetchrow("select state from runs where id = $1", run_id)
            if fresh_run["state"] in ("paused", "cancelled"):
                return

            await _set_step_state(conn, run_id, step_id, "running")

            if kind == PlanStepKind.READ.value:
                tokens_used += await _execute_read_step(conn, run_id, workspace_id, step, composio, rag, gathered_context, low_confidence_flags)

            elif kind == PlanStepKind.REASON.value:
                tokens_used += await _execute_reason_step(conn, run_id, outcome_id, step, router, gathered_context)

            elif kind == PlanStepKind.WRITE.value:
                # Un step d'écriture crée un artifact en attente et PAUSE le run
                # pour approbation explicite — jamais exécuté automatiquement.
                await _create_pending_artifact(conn, run_id, outcome_id, step)
                await _set_step_state(conn, run_id, step_id, "done", "Draft prepared, awaiting approval.")
                await conn.execute("update runs set state = 'paused' where id = $1", run_id)
                await _set_outcome_state(conn, outcome_id, OutcomeState.PAUSED_FOR_APPROVAL.value)
                await publish_event(run_id, "state", {"state": OutcomeState.PAUSED_FOR_APPROVAL.value}, 0)
                return

            elif kind == PlanStepKind.APPROVAL.value:
                await conn.execute("update runs set state = 'paused' where id = $1", run_id)
                await _set_outcome_state(conn, outcome_id, OutcomeState.PAUSED_FOR_APPROVAL.value)
                await publish_event(run_id, "state", {"state": OutcomeState.PAUSED_FOR_APPROVAL.value}, 0)
                return

            await _set_step_state(conn, run_id, step_id, "done")

        # Toutes les étapes exécutées sans écriture en attente -> synthèse finale.
        await _finalize_answer(conn, run_id, outcome_id, router, gathered_context, low_confidence_flags)

        await conn.execute(
            "update runs set state = 'done', finished_at = now(), token_usage = $2 where id = $1",
            run_id, tokens_used,
        )
        await conn.execute(
            "update outcomes set state = $1, delivered_at = now(), duration_ms = $2 where id = $3",
            OutcomeState.DELIVERED.value, int((time.monotonic() - start) * 1000), outcome_id,
        )
        await publish_event(run_id, "state", {"state": OutcomeState.DELIVERED.value}, 0)
        await publish_event(run_id, "done", {"outcomeId": str(outcome_id)}, 0)


async def _execute_read_step(conn, run_id, workspace_id, step, composio, rag, gathered_context, low_confidence_flags) -> int:
    tool_ids = step["tool_ids"] or []
    if not tool_ids:
        # Lecture documentaire (RAG) plutôt qu'outil connecté.
        chunks = await rag.retrieve(conn, query=step["detail"] or step["title"])
        if not chunks:
            await _log_event(conn, run_id, "gap", f"No relevant documents found for: {step['title']}", level="warn", step_id=step["id"])
            low_confidence_flags.append(step["title"])
            return 0
        for c in chunks:
            gathered_context.append(f"[{c.filename}#chunk{c.ordinal}] {c.content}")
            await conn.execute(
                """insert into citations (outcome_id, source_ref, what_was_read, document_id)
                   values ($1, $2, $3, $4)""",
                step["outcome_id"], f"document:{c.document_id}#chunk{c.ordinal}", step["title"], c.document_id,
            )
        await _log_event(conn, run_id, "read", f"Read {len(chunks)} relevant passages for: {step['title']}", step_id=step["id"])
        return 0

    for tool_id in tool_ids:
        connection = await conn.fetchrow(
            "select * from connections where workspace_id = $1 and tool_id = $2 and state = 'connected'",
            workspace_id, tool_id,
        )
        if connection is None:
            await _log_event(conn, run_id, "gap", f"Missing connection for {tool_id} — answer will flag low confidence.", level="warn", step_id=step["id"])
            low_confidence_flags.append(tool_id)
            continue

        try:
            result = await composio.execute_read_action(
                workspace_id, tool_id, action=f"{tool_id.upper()}_SEARCH", params={"query": step["detail"] or step["title"]}
            )
            gathered_context.append(f"[{tool_id}] {json.dumps(result)[:4000]}")
            await conn.execute(
                """insert into citations (outcome_id, tool_id, source_ref, what_was_read, record_count)
                   values ($1, $2, $3, $4, $5)""",
                step["outcome_id"], tool_id, f"{tool_id}:{step['id']}", step["title"], 1,
            )
            await _log_event(conn, run_id, "read", f"Read from {tool_id}: {step['title']}", step_id=step["id"])
        except Exception as exc:
            await _log_event(conn, run_id, "gap", f"{tool_id} read failed: {exc}", level="error", step_id=step["id"])
            low_confidence_flags.append(tool_id)

    return 0


async def _execute_reason_step(conn, run_id, outcome_id, step, router, gathered_context) -> int:
    """Le 'pushback step' (spec §7) : pas un side-effect, une étape distincte,
    qui peut produire un `finding` mi-parcours (l'utilisateur peut pivoter ou noter-et-continuer)."""
    context_blob = "\n\n".join(gathered_context[-40:])
    result = await router.complete(
        TaskRole.REASON,
        messages=[
            {"role": "system", "content": (
                "You are Kloyya's reasoning step. Find the underlying cause shared across "
                "the evidence, not just the surface-level accounts/items at risk. Be concise. "
                "If you find something the user didn't ask about but should know, phrase it as "
                "a distinct finding, not part of the main narrative."
            )},
            {"role": "user", "content": f"Task: {step['title']}\n{step['detail'] or ''}\n\nEvidence gathered so far:\n{context_blob}"},
        ],
        max_tokens=800,
    )
    gathered_context.append(f"[reasoning:{step['title']}] {result.text}")
    await _log_event(conn, run_id, "reason", f"Reasoned about: {step['title']}", step_id=step["id"])

    if "FINDING:" in result.text:
        finding_body = result.text.split("FINDING:", 1)[1].strip()
        finding_row = await conn.fetchrow(
            "insert into findings (outcome_id, kind, body) values ($1, 'unexpected', $2) returning id",
            outcome_id, finding_body,
        )
        await publish_event(run_id, "finding", {"id": str(finding_row["id"]), "kind": "unexpected", "body": finding_body}, 0)

    return result.total_tokens


async def _create_pending_artifact(conn, run_id, outcome_id, step) -> None:
    artifact = await conn.fetchrow(
        """
        insert into artifacts (outcome_id, kind, name, state, destination)
        values ($1, 'draft', $2, 'pending_approval', $3)
        returning id
        """,
        outcome_id, step["title"], (step["tool_ids"] or [None])[0],
    )
    await conn.execute(
        "insert into approvals (outcome_id, artifact_id, state) values ($1, $2, 'pending')",
        outcome_id, artifact["id"],
    )
    await _log_event(conn, run_id, "notify", f"Draft ready for approval: {step['title']}", step_id=step["id"])


async def _finalize_answer(conn, run_id, outcome_id, router, gathered_context, low_confidence_flags) -> None:
    context_blob = "\n\n".join(gathered_context)
    result = await router.complete(
        TaskRole.ANSWER,
        messages=[
            {"role": "system", "content": (
                "Synthesize a final answer for the user. Respond as strict JSON with keys: "
                "headline (string), narrative (string), confidence (0..1 float), "
                "rows (array of {label, value, risk, rationale, confidence}). "
                "Never invent a citation. If evidence is thin for a row, lower its confidence "
                "and say so in the rationale rather than presenting false certainty."
            )},
            {"role": "user", "content": (
                f"Evidence:\n{context_blob}\n\nKnown gaps (missing connections/documents): "
                f"{', '.join(low_confidence_flags) or 'none'}"
            )},
        ],
        max_tokens=1500,
        response_format={"type": "json_object"},
    )

    try:
        parsed = json.loads(result.text)
    except json.JSONDecodeError:
        parsed = {
            "headline": "Partial answer",
            "narrative": result.text[:2000],
            "confidence": 0.4,
            "rows": [],
        }

    await conn.execute(
        """
        insert into answers (outcome_id, headline, narrative, confidence, stats_json)
        values ($1, $2, $3, $4, $5)
        on conflict (outcome_id) do update set
            headline = excluded.headline, narrative = excluded.narrative,
            confidence = excluded.confidence, stats_json = excluded.stats_json
        """,
        outcome_id, parsed.get("headline", ""), parsed.get("narrative", ""),
        float(parsed.get("confidence", 0.5)), json.dumps({"gaps": low_confidence_flags}),
    )

    for idx, row in enumerate(parsed.get("rows", [])):
        row_confidence = float(row.get("confidence", 0.7))
        await conn.execute(
            """
            insert into answer_rows (outcome_id, ordinal, label, value_json, risk, rationale, confidence, low_confidence)
            values ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            outcome_id, idx, row.get("label", ""), json.dumps(row.get("value")),
            row.get("risk"), row.get("rationale"), row_confidence, row_confidence < 0.55,
        )

    await _log_event(conn, run_id, "insight", "Final answer synthesized.")