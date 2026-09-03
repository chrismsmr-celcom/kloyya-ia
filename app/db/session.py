"""
Pool asyncpg + primitive de contexte tenant.

Règle d'or (spec §8) : toute requête applicative passe par
`workspace_connection()`, qui pose `kloyya.workspace_id` en `SET LOCAL`
avant de rendre la connexion. Les policies RLS (002_rls_policies.sql)
s'appuient dessus. On n'écrit jamais une requête qui contourne ça pour
lire des données appartenant à un workspace.
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from uuid import UUID

import asyncpg

from app.config import get_settings

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> None:
    global _pool
    settings = get_settings()
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=2,
            max_size=20,
            command_timeout=30,
        )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call init_pool() at startup")
    return _pool


@asynccontextmanager
async def workspace_connection(workspace_id: UUID) -> AsyncIterator[asyncpg.Connection]:
    """
    Connexion avec le contexte tenant posé. Utiliser dans un `async with`
    et faire toutes les requêtes de la requête HTTP à l'intérieur de ce bloc,
    idéalement dans une seule transaction pour la cohérence.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("select set_config('kloyya.workspace_id', $1, true)", str(workspace_id))
            yield conn


@asynccontextmanager
async def system_connection() -> AsyncIterator[asyncpg.Connection]:
    """
    Connexion SANS contexte workspace — réservée aux jobs système
    (webhooks Stripe, cascade de révocation cross-check, migrations manuelles).
    Toute requête ici doit filtrer explicitement par workspace_id à la main.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn