"""Server-Sent Events (SSE) support for outcome streaming."""

from typing import AsyncGenerator
import asyncpg

async def replay_from_db(
    conn: asyncpg.Connection,
    run_id: str,
    last_event_id: int = 0
) -> AsyncGenerator[str, None]:
    """Replay events from the database starting from last_event_id."""
    # Placeholder pour Vercel Serverless (SSE natif non supporté sur Hobby)
    yield f'data: {{"type": "ready", "message": "SSE replay not supported in this environment"}}\n\n'


async def subscribe_live(run_id: str) -> AsyncGenerator[str, None]:
    """Subscribe to live events for a run."""
    # Placeholder pour Vercel Serverless
    yield f'data: {{"type": "listening", "message": "SSE live not supported in this environment"}}\n\n'
