from dataclasses import dataclass
from typing import AsyncIterator
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.core.security import AuthContext, verify_supabase_jwt
from app.db.session import workspace_connection

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id: UUID
    workspace_id: UUID
    email: str
    role: str
    tier: str


async def get_auth_context(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    """
    Authentification normale.

    En mode AUTH_BYPASS=true, cette dépendance n'est pas utilisée par
    get_current_user().
    """
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return verify_supabase_jwt(creds.credentials)


async def get_auth_context_sse(request: Request) -> AuthContext:
    token = request.query_params.get("access_token")

    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access token",
        )

    return verify_supabase_jwt(token)


async def _resolve_current_user(auth: AuthContext) -> CurrentUser:
    from app.db.session import system_connection

    async with system_connection() as conn:
        row = await conn.fetchrow(
            """
            select
                u.id as user_id,
                u.workspace_id,
                u.email,
                u.role,
                w.tier
            from users u
            join workspaces w on w.id = u.workspace_id
            where u.supabase_auth_id = $1
            """,
            auth.supabase_auth_id,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "No workspace provisioned for this account yet — "
                "call POST /api/onboarding/provision-workspace first."
            ),
        )

    return CurrentUser(
        user_id=row["user_id"],
        workspace_id=row["workspace_id"],
        email=row["email"],
        role=row["role"],
        tier=row["tier"],
    )


async def _get_test_user() -> CurrentUser:
    """
    UTILISÉ UNIQUEMENT POUR LES TESTS.

    Cherche automatiquement le premier workspace disponible.
    Aucun UUID n'est codé en dur.
    """
    from app.db.session import system_connection

    async with system_connection() as conn:
        row = await conn.fetchrow(
            """
            select
                u.id as user_id,
                u.workspace_id,
                u.email,
                u.role,
                w.tier
            from users u
            join workspaces w
                on w.id = u.workspace_id
            order by u.created_at asc
            limit 1
            """
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No test workspace/user exists in the database.",
        )

    return CurrentUser(
        user_id=row["user_id"],
        workspace_id=row["workspace_id"],
        email=row["email"],
        role=row["role"],
        tier=row["tier"],
    )


async def get_current_user(
    auth: AuthContext = Depends(get_auth_context),
) -> CurrentUser:
    """
    Auth normale ou bypass temporaire pour les tests.

    AUTH_BYPASS=true
        -> utilise automatiquement le premier workspace/user en DB.

    AUTH_BYPASS=false
        -> Supabase JWT obligatoire.
    """
    settings = get_settings()

    if settings.AUTH_BYPASS:
        return await _get_test_user()

    return await _resolve_current_user(auth)


async def get_current_user_sse(
    auth: AuthContext = Depends(get_auth_context_sse),
) -> CurrentUser:
    settings = get_settings()

    if settings.AUTH_BYPASS:
        return await _get_test_user()

    return await _resolve_current_user(auth)


async def get_tenant_conn(
    user: CurrentUser = Depends(get_current_user),
) -> AsyncIterator[asyncpg.Connection]:
    """
    Connexion DB avec le contexte RLS positionné sur le workspace.
    """
    async with workspace_connection(user.workspace_id) as conn:
        yield conn


async def get_tenant_conn_sse(
    user: CurrentUser = Depends(get_current_user_sse),
) -> AsyncIterator[asyncpg.Connection]:
    async with workspace_connection(user.workspace_id) as conn:
        yield conn
