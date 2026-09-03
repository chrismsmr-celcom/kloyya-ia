"""
Cascade de révocation (spec §5) — "Kloyya forgets what it read from that
source within the hour" est un engagement public, pas une formule marketing.

DELETE /api/connections/:toolId doit enclencher, dans l'ordre :
  1. Révocation du token chez le provider (Composio).
  2. Suppression des données brutes mises en cache pour cette source.
  3. Suppression des lignes `citations` qui pointent vers elle.
  4. Rétractation des `memory_facts` dérivés UNIQUEMENT de cette source.
     -> l'étape difficile : on ne rétracte que si CETTE source est la seule
        justification du fait (sinon on abîme une mémoire encore valide).
  5. Marquage des outcomes livrés affectés comme `sources_revoked`.
  6. Écriture dans audit_log.

Enfilée en job asynchrone (pas inline dans la requête HTTP DELETE) car
l'étape 4 peut nécessiter de parcourir beaucoup d'outcomes.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from app.services.composio_service import get_composio_service

log = structlog.get_logger()


async def revoke_connection_cascade(conn: asyncpg.Connection, workspace_id: UUID, tool_id: str, actor_user_id: UUID) -> None:
    connection = await conn.fetchrow(
        "select * from connections where workspace_id = $1 and tool_id = $2", workspace_id, tool_id
    )
    if connection is None:
        return

    composio = get_composio_service()

    # 1. Révoquer chez le provider.
    if connection["composio_connected_account_id"]:
        try:
            await composio.revoke(workspace_id, connection["composio_connected_account_id"])
        except Exception:
            log.exception("revocation.provider_revoke_failed", tool_id=tool_id, workspace_id=str(workspace_id))

    # 2. Données brutes en cache : dans ce schéma on ne persiste pas de cache brut
    #    séparé (les résultats de lecture vivent en mémoire pendant le run puis
    #    seulement les citations/answers dérivés sont stockés). Rien à purger ici
    #    au-delà de ce qui suit — documenté explicitement pour éviter un faux
    #    sentiment de complétude si un cache brut est ajouté plus tard.

    # 3. Citations pointant vers cette source.
    affected_outcomes = await conn.fetch(
        "select distinct outcome_id from citations where outcome_id in "
        "(select id from outcomes where workspace_id = $1) and tool_id = $2",
        workspace_id, tool_id,
    )
    await conn.execute(
        "delete from citations where tool_id = $1 and outcome_id in "
        "(select id from outcomes where workspace_id = $2)",
        tool_id, workspace_id,
    )

    # 4. Memory facts dérivés UNIQUEMENT de cette source.
    #    Un fact est rétracté seulement si TOUTES les citations de son
    #    outcome source pointaient vers ce tool_id (sinon un autre tool
    #    corrobore encore le fait).
    facts = await conn.fetch(
        """
        select mf.id, mf.source_outcome_id
        from memory_facts mf
        where mf.workspace_id = $1 and mf.retracted_at is null and mf.source_outcome_id is not null
        """,
        workspace_id,
    )
    for fact in facts:
        remaining_citation_sources = await conn.fetchval(
            "select count(*) from citations where outcome_id = $1 and tool_id is distinct from $2",
            fact["source_outcome_id"], tool_id,
        )
        if remaining_citation_sources == 0:
            await conn.execute(
                "update memory_facts set retracted_at = now() where id = $1", fact["id"]
            )

    # 5. Marquer les outcomes livrés affectés.
    for row in affected_outcomes:
        await conn.execute(
            "update outcomes set sources_revoked = true where id = $1", row["outcome_id"]
        )

    # Connection -> revoked
    await conn.execute(
        "update connections set state = 'revoked', revoked_at = now() where id = $1", connection["id"]
    )

    # 6. Audit log.
    await conn.execute(
        """
        insert into audit_log (workspace_id, actor, action, target, meta_json)
        values ($1, $2, 'connection.revoked_cascade', $3, $4)
        """,
        workspace_id, actor_user_id, tool_id,
        '{"affected_outcomes": %d}' % len(affected_outcomes),
    )