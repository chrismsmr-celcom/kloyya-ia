"""
Enforcement des tiers (spec webapp §6). Vérifié au démarrage du run
(POST /run), jamais à la création de l'outcome — les utilisateurs doivent
pouvoir rédiger librement.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.enums import TIER_LIMITS


async def assert_can_start_run(conn: asyncpg.Connection, workspace_id: UUID) -> None:
    workspace = await conn.fetchrow(
        "select tier, free_period_ends_at from workspaces where id = $1", workspace_id
    )
    tier = workspace["tier"]
    limits = TIER_LIMITS[tier]

    if limits["runs_per_month_after_trial"] is None:
        await _increment_usage(conn, workspace_id)
        return

    now = datetime.now(timezone.utc)
    free_period_ends_at = workspace["free_period_ends_at"]
    if free_period_ends_at and now < free_period_ends_at:
        await _increment_usage(conn, workspace_id)
        return  # encore dans les 30 jours gratuits illimités

    period_start = date(now.year, now.month, 1)
    row = await conn.fetchrow(
        "select runs_used from usage_counters where workspace_id = $1 and period_start = $2",
        workspace_id, period_start,
    )
    runs_used = row["runs_used"] if row else 0
    cap = limits["runs_per_month_after_trial"]

    if runs_used >= cap:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Free tier limit reached ({cap} runs/month). Upgrade to continue.",
                "unblocking_tier": "starter",
            },
        )

    await _increment_usage(conn, workspace_id, period_start=period_start)


async def _increment_usage(conn: asyncpg.Connection, workspace_id: UUID, period_start: date | None = None) -> None:
    period_start = period_start or date.today().replace(day=1)
    await conn.execute(
        """
        insert into usage_counters (workspace_id, period_start, runs_used)
        values ($1, $2, 1)
        on conflict (workspace_id, period_start)
        do update set runs_used = usage_counters.runs_used + 1
        """,
        workspace_id, period_start,
    )


async def assert_connection_slot_available(conn: asyncpg.Connection, workspace_id: UUID) -> None:
    workspace = await conn.fetchrow("select tier from workspaces where id = $1", workspace_id)
    limits = TIER_LIMITS[workspace["tier"]]
    if limits["connections"] is None:
        return
    count = await conn.fetchval(
        "select count(*) from connections where workspace_id = $1 and state = 'connected'", workspace_id
    )
    if count >= limits["connections"]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Connection limit reached for this tier ({limits['connections']}).",
        )