"""
Vérification des JWT émis par Supabase Auth. Kloyya n'implémente pas son
propre auth : signup/login/OAuth/SSO passent par Supabase Auth (voir
kloyya-landing-backend-spec.md §4 — Supabase remplace le service "landing
identity" custom décrit dans la spec). Ce module vérifie juste la
signature et extrait `sub` (= auth.users.id).
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from jose import jwt, JWTError

from app.config import get_settings


@dataclass
class AuthContext:
    supabase_auth_id: UUID
    email: str
    raw_claims: dict


def verify_supabase_jwt(token: str) -> AuthContext:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired session token: {exc}",
        )

    sub = claims.get("sub")
    email = claims.get("email")
    if not sub or not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")

    return AuthContext(supabase_auth_id=UUID(sub), email=email, raw_claims=claims)