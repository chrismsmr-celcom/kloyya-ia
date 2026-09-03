"""
Onboarding (spec landing §5). Auth elle-même est déléguée à Supabase Auth ;
ce endpoint ne fait que la partie propre à Kloyya : persona -> workspace,
et déclenche les URLs d'autorisation Composio pour les tools demandés.

Toutes les listes ROLES/GOALS/RECO par persona sont versionnées ici,
côté serveur (spec: "keep those three lists server-side ... so growth
can tune them without a client deploy") plutôt que dupliquées côté client.
Elles doivent être extraites verbatim de la classe logique du prototype
(`ROLES`, `GOALS`, `RECO`) au moment de l'intégration — placeholders ci-dessous.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import AuthContext, verify_supabase_jwt
from app.deps import CurrentUser, get_auth_context, get_current_user
from app.db.session import system_connection
from app.models.schemas import OnboardingRequest
from app.services.composio_service import get_composio_service

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@router.post("/provision-workspace", status_code=201)
async def provision_workspace(auth: AuthContext = Depends(get_auth_context)):
    """
    Appelé une fois juste après `supabase.auth.signUp()`, avant d'entrer dans
    /onboarding. Crée le workspace + la ligne `users` liée au compte
    Supabase. Idempotent : si l'utilisateur a déjà un workspace, le renvoie.
    """
    async with system_connection() as conn:  # type: asyncpg.Connection
        existing = await conn.fetchrow(
            "select workspace_id from users where supabase_auth_id = $1", auth.supabase_auth_id
        )
        if existing:
            return {"workspaceId": str(existing["workspace_id"]), "created": False}

        workspace = await conn.fetchrow(
            "insert into workspaces (name, tier) values ($1, 'free') returning id",
            auth.email.split("@")[0],
        )
        await conn.execute(
            """
            insert into users (workspace_id, supabase_auth_id, email, role, identity_provider)
            values ($1, $2, $3, 'owner', 'password')
            """,
            workspace["id"], auth.supabase_auth_id, auth.email,
        )
    return {"workspaceId": str(workspace["id"]), "created": True}

# TODO intégration : remplacer par le contenu exact de ROLES/GOALS/RECO
# extrait de Kloyya-prototype.html, clé par persona ('work'|'business'|'school'|'life').
PERSONA_CONFIG: dict[str, dict] = {
    "work": {
        "roles": ["Chief of Staff", "Operations lead", "Manager", "Individual contributor"],
        "suggested_outcomes": ["Prep my QBR", "Find at-risk accounts", "Summarize this week's Slack noise"],
        "recommended_tools": ["slack", "gmail", "gcal", "notion"],
    },
    "business": {
        "roles": ["Founder", "Revenue lead", "Ops"],
        "suggested_outcomes": ["Find churn risk", "Draft investor update", "Pipeline health check"],
        "recommended_tools": ["salesforce", "hubspot", "gmail", "slack"],
    },
    "school": {
        "roles": ["Student", "Researcher", "Teaching assistant"],
        "suggested_outcomes": ["Summarize my readings", "Track project deadlines"],
        "recommended_tools": ["gdrive", "notion", "gcal"],
    },
    "life": {
        "roles": ["Individual", "Household manager"],
        "suggested_outcomes": ["Plan my week", "Track a big purchase decision"],
        "recommended_tools": ["gmail", "gcal", "whatsapp"],
    },
}


@router.get("/persona-config/{persona}")
async def get_persona_config(persona: str):
    return PERSONA_CONFIG.get(persona, PERSONA_CONFIG["work"])


@router.post("")
async def complete_onboarding(body: OnboardingRequest, user: CurrentUser = Depends(get_current_user)):
    async with system_connection() as conn:  # type: asyncpg.Connection
        await conn.execute(
            "update workspaces set persona = $1, role = $2, first_outcome = $3 where id = $4",
            body.persona, body.role, body.first_outcome, user.workspace_id,
        )

    composio = get_composio_service()
    connect_urls = {}
    for tool_id in body.requested_tools:
        handle = await composio.start_authorization(user.workspace_id, tool_id)
        connect_urls[tool_id] = handle.redirect_url

    return {"workspaceId": str(user.workspace_id), "connectUrls": connect_urls}