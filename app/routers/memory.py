from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.deps import CurrentUser, get_current_user, get_tenant_conn

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
async def list_memory(conn: asyncpg.Connection = Depends(get_tenant_conn)):
    rows = await conn.fetch(
        "select * from memory_facts where retracted_at is null order by created_at desc"
    )
    return [dict(r) for r in rows]


@router.delete("/{fact_id}")
async def retract_memory(
    fact_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_tenant_conn),
):
    row = await conn.fetchrow(
        "update memory_facts set retracted_at = now() where id = $1 returning id", fact_id
    )
    if row is None:
        raise HTTPException(404, "Memory fact not found")
    await conn.execute(
        "insert into audit_log (workspace_id, actor, action, target, meta_json) values ($1, $2, 'memory.retracted', $3, '{}')",
        user.workspace_id, user.user_id, str(fact_id),
    )
    return {"ok": True}