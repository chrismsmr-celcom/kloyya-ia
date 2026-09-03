from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends

from app.deps import get_tenant_conn

router = APIRouter(prefix="/api/impact", tags=["impact"])


@router.get("")
async def impact_dashboard(conn: asyncpg.Connection = Depends(get_tenant_conn)):
    outcomes_by_state = await conn.fetch(
        "select state, count(*) as n from outcomes group by state"
    )
    avg_duration = await conn.fetchval(
        "select avg(duration_ms) from outcomes where duration_ms is not null"
    )
    total_delivered = await conn.fetchval(
        "select count(*) from outcomes where state = 'delivered'"
    )
    active_connections = await conn.fetchval(
        "select count(*) from connections where state = 'connected'"
    )
    writes_executed = await conn.fetchval(
        "select count(*) from artifacts where state = 'executed'"
    )

    return {
        "outcomesByState": {r["state"]: r["n"] for r in outcomes_by_state},
        "avgDurationMs": float(avg_duration) if avg_duration else None,
        "totalDelivered": total_delivered,
        "activeConnections": active_connections,
        "writesExecuted": writes_executed,
    }