from dataclasses import dataclass
from typing import AsyncIterator
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import AuthContext, verify_supabase_jwt
from app.db.session import workspace_connection

bearer_scheme = HTTPBearer(auto_error=True)


@dataclass
class CurrentUser:
    user_id: UUID
    workspace_id: UUID
    email: str
    role: str  # 'owner' | 'admin' | 'member'
    tier: str


async def get_auth_context(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthContext:
    return verify_supabase_jwt(creds.credentials)


async def get_auth_context_sse(request: Request) -> AuthContext:
    """
    Variante pour l'endpoint SSE : `EventSource` natif ne permet pas d'envoyer
    un header `Authorization`, donc on accepte le token en query param
    (`?access_token=`) en plus du header Bearer classique. N'utiliser cette
    dépendance QUE pour /stream — tout le reste de l'API garde le header
    obligatoire (`get_auth_context`).
    """
    token = request.query_params.get("access_token")
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")
    return verify_supabase_jwt(token)


async def _resolve_current_user(auth: AuthContext) -> CurrentUser:
    from app.db.session import system_connection

    async with system_connection() as conn:  # type: asyncpg.Connection
        row = await conn.fetchrow(
            """
            select u.id as user_id, u.workspace_id, u.email, u.role, w.tier
            from users u
            join workspaces w on w.id = u.workspace_id
            where u.supabase_auth_id = $1
            """,
            auth.supabase_auth_id,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No workspace provisioned for this account yet — call POST /api/onboarding/provision-workspace first.",
        )

    return CurrentUser(
        user_id=row["user_id"],
        workspace_id=row["workspace_id"],
        email=row["email"],
        role=row["role"],
        tier=row["tier"],
    )


async def get_current_user(auth: AuthContext = Depends(get_auth_context)) -> CurrentUser:
    return await _resolve_current_user(auth)


async def get_current_user_sse(auth: AuthContext = Depends(get_auth_context_sse)) -> CurrentUser:
    return await _resolve_current_user(auth)


async def get_tenant_conn(
    user: CurrentUser = Depends(get_current_user),
) -> AsyncIterator[asyncpg.Connection]:
    """Connexion DB avec le contexte RLS déjà positionné sur `user.workspace_id`.
    C'est la dépendance à utiliser dans presque tous les routers."""
    async with workspace_connection(user.workspace_id) as conn:
        yield conn


async def get_tenant_conn_sse(
    user: CurrentUser = Depends(get_current_user_sse),
) -> AsyncIterator[asyncpg.Connection]:
    async with workspace_connection(user.workspace_id) as conn:
        yield conn