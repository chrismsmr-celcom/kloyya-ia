from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.deps import CurrentUser, get_current_user, get_tenant_conn
from app.models.schemas import ConnectionScopesUpdate
from app.services.composio_service import get_composio_service
from app.services.entitlements import assert_connection_slot_available
from app.services.revocation import revoke_connection_cascade

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
async def list_connections(conn: asyncpg.Connection = Depends(get_tenant_conn)):
    rows = await conn.fetch("select * from connections order by tool_id")
    return [dict(r) for r in rows]


@router.post("/{tool_id}/authorize")
async def authorize(
    tool_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    await assert_connection_slot_available(conn, user.workspace_id)
    composio = get_composio_service()
    handle = await composio.start_authorization(user.workspace_id, tool_id)

    await conn.execute(
        """
        insert into connections (workspace_id, tool_id, state, composio_connected_account_id, granted_by)
        values ($1, $2, 'pending', $3, $4)
        on conflict (workspace_id, tool_id) do update set
            state = 'pending', composio_connected_account_id = excluded.composio_connected_account_id
        """,
        user.workspace_id, tool_id, handle.connected_account_id, user.user_id,
    )
    return RedirectResponse(handle.redirect_url, status_code=302)


@router.get("/{tool_id}/callback")
async def oauth_callback(
    tool_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    settings = get_settings()
    composio = get_composio_service()
    connection = await conn.fetchrow(
        "select * from connections where workspace_id = $1 and tool_id = $2", user.workspace_id, tool_id
    )
    if connection is None or not connection["composio_connected_account_id"]:
        raise HTTPException(400, "No pending authorization for this tool.")

    is_active = await composio.finalize_authorization(user.workspace_id, connection["composio_connected_account_id"])
    new_state = "connected" if is_active else "error"

    await conn.execute(
        "update connections set state = $1, granted_at = now(), last_sync_at = now() where id = $2",
        new_state, connection["id"],
    )
    await conn.execute(
        "insert into audit_log (workspace_id, actor, action, target, meta_json) values ($1, $2, 'connection.granted', $3, '{}')",
        user.workspace_id, user.user_id, tool_id,
    )
    return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/#connections?tool={tool_id}&status={new_state}", status_code=302)


@router.patch("/{tool_id}/scopes")
async def update_scopes(
    tool_id: str, body: ConnectionScopesUpdate, conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    connection = await conn.fetchrow(
        "select id from connections where workspace_id = current_workspace_id() and tool_id = $1", tool_id
    )
    if connection is None:
        raise HTTPException(404, "Connection not found")

    await conn.execute("delete from connection_scopes where connection_id = $1", connection["id"])
    for resource in body.resources:
        await conn.execute(
            "insert into connection_scopes (connection_id, resource, allowed) values ($1, $2, true)",
            connection["id"], resource,
        )
    return {"ok": True}


@router.delete("/{tool_id}")
async def revoke_connection(
    tool_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    """Déclenche la cascade complète décrite en spec §5 — pas une simple mise à
    jour de statut. Fait dans la transaction de la requête pour ce scaffold ;
    en prod, préférer une queue dédiée si le volume d'outcomes est important."""
    await revoke_connection_cascade(conn, user.workspace_id, tool_id, user.user_id)
    return {"ok": True, "revoked": tool_id}