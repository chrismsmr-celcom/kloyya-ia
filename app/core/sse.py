"""Server-Sent Events (SSE) and Redis stubs for Vercel Serverless compatibility."""

from typing import AsyncGenerator, Any
import asyncpg

# --- STUBS POUR REDIS (pour satisfaire l'import de run_engine.py) ---
# Sur Vercel Serverless, une vraie connexion Redis persistante est complexe.
# Ces stubs empêchent le crash au démarrage. Pour la prod, envisage Upstash Redis.

def get_redis() -> Any:
    """Retourne None ou un mock pour éviter le crash à l'import."""
    return None

async def publish_event(run_id: str, event_type: str, data: dict) -> None:
    """Stub: Ne fait rien en environnement serverless sans Upstash."""
    pass

# --- STUBS POUR SSE (pour satisfaire l'import de outcomes.py) ---

async def replay_from_db(
    conn: asyncpg.Connection,
    run_id: str,
    last_event_id: int = 0
) -> AsyncGenerator[str, None]:
    """Replay events from the database starting from last_event_id."""
    yield f'data: {{"type": "ready", "message": "SSE replay stubbed for Vercel Serverless"}}\n\n'


async def subscribe_live(run_id: str) -> AsyncGenerator[str, None]:
    """Subscribe to live events for a run."""
    yield f'data: {{"type": "listening", "message": "SSE live stubbed for Vercel Serverless"}}\n\n'
