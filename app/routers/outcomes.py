"""
Le state machine complet de la spec webapp §1 et l'API §3.

    draft -> clarifying -> planned -> running -> paused_for_approval -> delivered
                                          |
                                   blocked / failed / cancelled

Le client n'écrit jamais l'état directement : chaque endpoint appelle une
action serveur qui décide de la transition et la journalise.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from sse_starlette.sse import EventSourceResponse

from app.core.enums import OutcomeState
#from app.core.sse import replay_from_db, subscribe_live
from app.deps import CurrentUser, get_current_user, get_tenant_conn, get_tenant_conn_sse
from app.models.schemas import (
    ApproveRequest, ClarifyRequest, CreateOutcomeRequest, FindingResponseRequest,
    OutcomeOut, UpdatePlanRequest,
)
from app.services.composio_service import get_composio_service
from app.services.entitlements import assert_can_start_run
from app.services.llm_router import TaskRole, get_llm_router
from app.services.rag_service import get_rag_service
from app.services.run_engine import enqueue_run
from app.services.transcription import transcribe_audio

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OutcomeOut)
async def create_outcome(
    body: CreateOutcomeRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    workspace = await conn.fetchrow(
        "select persona, role, first_outcome from workspaces where id = $1", user.workspace_id
    )
    row = await conn.fetchrow(
        """
        insert into outcomes (workspace_id, created_by, title, state, persona_context, scope_json)
        values ($1, $2, $3, 'draft', $4, $5)
        returning id, title, state, created_at, started_at, delivered_at, duration_ms, sources_revoked
        """,
        user.workspace_id, user.user_id, body.title,
        json.dumps({"persona": workspace["persona"], "role": workspace["role"]}),
        json.dumps(body.scope or {}),
    )
    return OutcomeOut(**dict(row))


@router.post("/{outcome_id}/clarify", response_model=OutcomeOut)
async def clarify_outcome(
    outcome_id: UUID,
    body: ClarifyRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    """
    Exactement une question, avec des options concrètes, générée depuis le
    texte de l'outcome + la persona du workspace (spec §7). Si le modèle n'a
    rien à demander, on saute directement à `planned`.
    """
    outcome = await _get_outcome_or_404(conn, outcome_id)
    if outcome["state"] not in (OutcomeState.DRAFT.value, OutcomeState.CLARIFYING.value):
        raise HTTPException(400, "Outcome is not awaiting clarification.")

    pending_question = await conn.fetchrow(
        "select * from outcome_questions where outcome_id = $1 and answer is null order by created_at desc limit 1",
        outcome_id,
    )
    if pending_question:
        await conn.execute(
            "update outcome_questions set answer = $1, answered_at = now() where id = $2",
            body.answer, pending_question["id"],
        )

    router_llm = get_llm_router()
    plan_result = await _generate_plan(conn, router_llm, outcome, user)
    return OutcomeOut(**dict(plan_result))


async def _generate_plan(conn, router_llm, outcome, user: CurrentUser):
    workspace = await conn.fetchrow(
        "select persona, role, first_outcome from workspaces where id = $1", user.workspace_id
    )
    connections = await conn.fetch(
        "select tool_id from connections where workspace_id = $1 and state = 'connected'", user.workspace_id
    )
    connected_tools = [c["tool_id"] for c in connections]

    llm_response = await router_llm.complete(
        TaskRole.PLAN,
        messages=[
            {"role": "system", "content": (
                "You are Kloyya's planner. Produce a JSON array of plan steps to reach the "
                "user's stated outcome. Each step: {title, detail, kind: 'read'|'reason'|'write'|'approval', "
                "tool_ids: string[] (subset of connected tools, or [] for a document/RAG read), "
                "requires_approval: bool}. Always include exactly one 'reason' step that looks for "
                "the shared underlying cause, not just surface symptoms. 'write' steps always need "
                "requires_approval=true. Connected tools available: " + ", ".join(connected_tools)
            )},
            {"role": "user", "content": f"Persona: {workspace['persona']} / {workspace['role']}\nOutcome: {outcome['title']}"},
        ],
        response_format={"type": "json_object"},
        max_tokens=1200,
    )

    try:
        steps = json.loads(llm_response.text)
        if isinstance(steps, dict):
            steps = steps.get("steps", [])
    except json.JSONDecodeError:
        steps = []

    await conn.execute("delete from plan_steps where outcome_id = $1", outcome["id"])
    for idx, step in enumerate(steps):
        await conn.execute(
            """
            insert into plan_steps (outcome_id, ordinal, title, detail, kind, tool_ids, requires_approval)
            values ($1, $2, $3, $4, $5, $6, $7)
            """,
            outcome["id"], idx, step.get("title", f"Step {idx+1}"), step.get("detail"),
            step.get("kind", "read"), step.get("tool_ids", []), bool(step.get("requires_approval")),
        )

    return await conn.fetchrow(
        """
        update outcomes set state = 'planned' where id = $1
        returning id, title, state, created_at, started_at, delivered_at, duration_ms, sources_revoked
        """,
        outcome["id"],
    )


@router.get("/{outcome_id}/plan")
async def get_plan(outcome_id: UUID, conn: asyncpg.Connection = Depends(get_tenant_conn)):
    await _get_outcome_or_404(conn, outcome_id)
    rows = await conn.fetch("select * from plan_steps where outcome_id = $1 order by ordinal", outcome_id)
    return [dict(r) for r in rows]


@router.patch("/{outcome_id}/plan")
async def update_plan(
    outcome_id: UUID, body: UpdatePlanRequest, conn: asyncpg.Connection = Depends(get_tenant_conn)
):
    """L'utilisateur édite le plan. Une étape supprimée ('skipped') ne s'exécute
    jamais — on trace `edited_by_user` pour mesurer la qualité du planner (spec §7)."""
    await _get_outcome_or_404(conn, outcome_id)
    for step in body.steps:
        fields, values = [], []
        if step.title is not None:
            fields.append("title = $%d" % (len(values) + 1)); values.append(step.title)
        if step.detail is not None:
            fields.append("detail = $%d" % (len(values) + 1)); values.append(step.detail)
        if step.state is not None:
            fields.append("state = $%d" % (len(values) + 1)); values.append(step.state)
        fields.append("edited_by_user = true")
        if fields:
            values.append(step.id)
            await conn.execute(f"update plan_steps set {', '.join(fields)} where id = ${len(values)}", *values)

    rows = await conn.fetch("select * from plan_steps where outcome_id = $1 order by ordinal", outcome_id)
    return [dict(r) for r in rows]


@router.post("/{outcome_id}/run", status_code=status.HTTP_201_CREATED)
async def start_run(
    outcome_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    idempotency_key = request.headers.get("Idempotency-Key")
    outcome = await _get_outcome_or_404(conn, outcome_id)
    if outcome["state"] not in (OutcomeState.PLANNED.value, OutcomeState.PAUSED_FOR_APPROVAL.value):
        raise HTTPException(400, "Outcome must be planned before running.")

    await assert_can_start_run(conn, user.workspace_id)

    if idempotency_key:
        existing = await conn.fetchrow("select id from runs where idempotency_key = $1", idempotency_key)
        if existing:
            return {"id": str(existing["id"]), "outcomeId": str(outcome_id), "state": "queued", "deduped": True}

    run = await conn.fetchrow(
        "insert into runs (outcome_id, state, idempotency_key) values ($1, 'queued', $2) returning id",
        outcome_id, idempotency_key,
    )
    await enqueue_run(run["id"], user.workspace_id)
    return {"id": str(run["id"]), "outcomeId": str(outcome_id), "state": "queued"}


@router.get("/{outcome_id}/stream")
async def stream_outcome(outcome_id: UUID):
    # SSE n'est pas supporté sur Vercel Serverless (timeout 10s)
    # Voir README pour les alternatives (Upstash QStash, etc.)
    raise HTTPException(
        status_code=501, 
        detail="SSE streaming is not supported in this Vercel serverless deployment."
    )
    """SSE — spec §4. Honore `Last-Event-ID` pour rejouer depuis la DB avant
    de rebrancher le direct, comme demandé explicitement."""
    run = await conn.fetchrow(
        "select id from runs where outcome_id = $1 order by started_at desc nulls last limit 1", outcome_id
    )
    if run is None:
        raise HTTPException(404, "No run for this outcome yet.")
    run_id = run["id"]
    last_event_id = request.headers.get("Last-Event-ID")

    async def event_generator():
        if last_event_id:
            async for evt in replay_from_db(conn, run_id, int(last_event_id)):
                yield evt
        async for evt in subscribe_live(run_id):
            if await request.is_disconnected():
                break
            yield evt

    return EventSourceResponse(event_generator())


@router.post("/{outcome_id}/pause")
async def pause_outcome(outcome_id: UUID, conn: asyncpg.Connection = Depends(get_tenant_conn)):
    await conn.execute(
        "update runs set state = 'paused' where outcome_id = $1 and state = 'running'", outcome_id
    )
    return {"ok": True}


@router.post("/{outcome_id}/cancel")
async def cancel_outcome(outcome_id: UUID, conn: asyncpg.Connection = Depends(get_tenant_conn)):
    await conn.execute("update runs set state = 'cancelled' where outcome_id = $1", outcome_id)
    await conn.execute("update outcomes set state = 'cancelled' where id = $1", outcome_id)
    return {"ok": True}


@router.post("/{outcome_id}/findings/{finding_id}")
async def respond_to_finding(
    outcome_id: UUID, finding_id: UUID, body: FindingResponseRequest,
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    if body.response not in ("pivot", "note"):
        raise HTTPException(422, "response must be 'pivot' or 'note'")
    await conn.execute(
        "update findings set user_response = $1 where id = $2 and outcome_id = $3",
        body.response, finding_id, outcome_id,
    )
    return {"ok": True}


@router.get("/{outcome_id}")
async def get_outcome_detail(outcome_id: UUID, conn: asyncpg.Connection = Depends(get_tenant_conn)):
    outcome = await _get_outcome_or_404(conn, outcome_id)
    answer = await conn.fetchrow("select * from answers where outcome_id = $1", outcome_id)
    rows = await conn.fetch("select * from answer_rows where outcome_id = $1 order by ordinal", outcome_id)
    citations = await conn.fetch("select * from citations where outcome_id = $1", outcome_id)
    artifacts = await conn.fetch("select * from artifacts where outcome_id = $1", outcome_id)
    findings = await conn.fetch("select * from findings where outcome_id = $1", outcome_id)

    return {
        "outcome": dict(outcome),
        "answer": dict(answer) if answer else None,
        "rows": [dict(r) for r in rows],
        "citations": [dict(c) for c in citations],
        "artifacts": [dict(a) for a in artifacts],
        "findings": [dict(f) for f in findings],
    }


@router.post("/{outcome_id}/approve")
async def approve_artifacts(
    outcome_id: UUID, body: ApproveRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    """
    Exécute les writes approuvés. Le texte final montré à l'utilisateur est
    EXACTEMENT celui envoyé au provider — aucune instruction issue du contenu
    d'un outil ne peut altérer ce texte après approbation (spec §7).
    """
    composio = get_composio_service()
    executed = []
    for artifact_id in body.artifact_ids:
        artifact = await conn.fetchrow("select * from artifacts where id = $1 and outcome_id = $2", artifact_id, outcome_id)
        if artifact is None:
            continue

        await conn.execute("update approvals set state = 'approved', decided_by = $1, decided_at = now() where artifact_id = $2", user.user_id, artifact_id)

        connection = await conn.fetchrow(
            "select * from connections where workspace_id = $1 and tool_id = $2 and state = 'connected'",
            user.workspace_id, artifact["destination"],
        )
        if connection:
            try:
                await composio.execute_write_action(
                    user.workspace_id, connection["composio_connected_account_id"], artifact["destination"],
                    action=f"{artifact['destination'].upper()}_SEND",
                    params=artifact["payload"] or {},
                )
                await conn.execute("update artifacts set state = 'executed' where id = $1", artifact_id)
                executed.append(str(artifact_id))
            except Exception as exc:
                await conn.execute("update artifacts set state = 'rejected' where id = $1", artifact_id)
                raise HTTPException(502, f"Write failed for artifact {artifact_id}: {exc}")

        await conn.execute(
            "insert into audit_log (workspace_id, actor, action, target, meta_json) values ($1, $2, 'artifact.approved', $3, '{}')",
            user.workspace_id, user.user_id, str(artifact_id),
        )

    # Reprendre le run si toutes les approbations pendantes sont réglées.
    still_pending = await conn.fetchval(
        "select count(*) from approvals where outcome_id = $1 and state = 'pending'", outcome_id
    )
    if still_pending == 0:
        run = await conn.fetchrow("select id from runs where outcome_id = $1 order by started_at desc limit 1", outcome_id)
        if run:
            await conn.execute("update runs set state = 'running' where id = $1", run["id"])
            await get_run_engine_module().enqueue_run(run["id"], user.workspace_id)

    return {"executed": executed}


def get_run_engine_module():
    from app.services import run_engine
    return run_engine


@router.get("")
async def list_outcomes(
    state: str | None = None, cursor: str | None = None,
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    if state:
        rows = await conn.fetch(
            "select id, title, state, created_at, started_at, delivered_at, duration_ms, sources_revoked "
            "from outcomes where state = $1 order by created_at desc limit 50", state
        )
    else:
        rows = await conn.fetch(
            "select id, title, state, created_at, started_at, delivered_at, duration_ms, sources_revoked "
            "from outcomes order by created_at desc limit 50"
        )
    return [dict(r) for r in rows]


@router.post("/{outcome_id}/transcribe")
async def transcribe(
    outcome_id: UUID, audio: UploadFile = File(...), conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    await _get_outcome_or_404(conn, outcome_id)
    raw = await audio.read()
    text = await transcribe_audio(raw, content_type=audio.content_type or "audio/webm")
    return {"text": text}


async def _get_outcome_or_404(conn: asyncpg.Connection, outcome_id: UUID):
    outcome = await conn.fetchrow("select * from outcomes where id = $1", outcome_id)
    if outcome is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Outcome not found")
    return outcome
