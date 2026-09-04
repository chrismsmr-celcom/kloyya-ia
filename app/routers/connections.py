from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from app.config import get_settings
from app.deps import CurrentUser, get_current_user, get_tenant_conn
from app.models.schemas import ConnectionScopesUpdate
from app.services.composio_service import get_composio_service
from app.services.entitlements import assert_connection_slot_available
from app.services.revocation import revoke_connection_cascade

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
async def list_connections(
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    rows = await conn.fetch(
        """
        select
            id,
            tool_id,
            state,
            composio_connected_account_id,
            granted_by,
            granted_at,
            last_sync_at
        from connections
        order by tool_id
        """
    )

    return [dict(row) for row in rows]


@router.post("/{tool_id}/authorize")
async def authorize(
    tool_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    await assert_connection_slot_available(
        conn,
        user.workspace_id,
    )

    composio = get_composio_service()

    handle = await composio.start_authorization(
        user.workspace_id,
        tool_id,
    )

    await conn.execute(
        """
        insert into connections (
            workspace_id,
            tool_id,
            state,
            composio_connected_account_id,
            granted_by
        )
        values ($1, $2, 'pending', $3, $4)
        on conflict (workspace_id, tool_id)
        do update set
            state = 'pending',
            composio_connected_account_id =
                excluded.composio_connected_account_id
        """,
        user.workspace_id,
        tool_id,
        handle.connected_account_id,
        user.user_id,
    )

    return {
        "redirect_url": handle.redirect_url,
        "tool_id": tool_id,
        "status": "pending",
    }


@router.get("/{tool_id}/callback")
async def oauth_callback(
    tool_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    settings = get_settings()
    composio = get_composio_service()

    connection = await conn.fetchrow(
        """
        select *
        from connections
        where workspace_id = $1
          and tool_id = $2
        """,
        user.workspace_id,
        tool_id,
    )

    if connection is None:
        raise HTTPException(
            status_code=400,
            detail="No pending authorization for this tool.",
        )

    connected_account_id = connection[
        "composio_connected_account_id"
    ]

    if not connected_account_id:
        raise HTTPException(
            status_code=400,
            detail="No pending Composio authorization.",
        )

    is_active = await composio.finalize_authorization(
        user.workspace_id,
        connected_account_id,
    )

    new_state = "connected" if is_active else "error"

    await conn.execute(
        """
        update connections
        set
            state = $1,
            granted_at = now(),
            last_sync_at = now()
        where id = $2
        """,
        new_state,
        connection["id"],
    )

    await conn.execute(
        """
        insert into audit_log (
            workspace_id,
            actor,
            action,
            target,
            meta_json
        )
        values (
            $1,
            $2,
            'connection.granted',
            $3,
            '{}'
        )
        """,
        user.workspace_id,
        user.user_id,
        tool_id,
    )

    return {
        "ok": True,
        "tool_id": tool_id,
        "status": new_state,
        "frontend": settings.FRONTEND_ORIGIN,
    }


@router.patch("/{tool_id}/scopes")
async def update_scopes(
    tool_id: str,
    body: ConnectionScopesUpdate,
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    connection = await conn.fetchrow(
        """
        select id
        from connections
        where workspace_id = current_workspace_id()
          and tool_id = $1
        """,
        tool_id,
    )

    if connection is None:
        raise HTTPException(
            status_code=404,
            detail="Connection not found",
        )

    await conn.execute(
        """
        delete from connection_scopes
        where connection_id = $1
        """,
        connection["id"],
    )

    for resource in body.resources:
        await conn.execute(
            """
            insert into connection_scopes (
                connection_id,
                resource,
                allowed
            )
            values ($1, $2, true)
            """,
            connection["id"],
            resource,
        )

    return {"ok": True}


@router.delete("/{tool_id}")
async def revoke_connection(
    tool_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    await revoke_connection_cascade(
        conn,
        user.workspace_id,
        tool_id,
        user.user_id,
    )

    return {
        "ok": True,
        "revoked": tool_id,
    }
