"""
Intégration Composio — auth et exécution des 14 outils (spec §5) :
Slack, Gmail, Google Calendar, Google Drive, Notion, Linear, Jira, GitHub,
Figma, Salesforce, HubSpot, Asana, WhatsApp Business, Instagram.

Composio gère :
  - l'OAuth (authorize_url / callback / refresh) pour chaque provider
  - l'exécution d'actions ("read this Slack channel", "list Gmail threads"...)
  - le stockage chiffré des tokens côté Composio (on ne stocke chez nous que
    le `composio_connected_account_id`, jamais le token brut — spec §5 :
    "store tokens encrypted at rest ... per workspace")

Read-only par défaut : on ne demande que les scopes de lecture les plus
étroits à la connexion. Les scopes d'écriture sont demandés PAR OUTCOME au
moment de l'approbation, et expirent avec cet outcome (jamais de grant
d'écriture permanent) — voir approve_write_scope().
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from composio import Composio, App, Action

from app.config import get_settings

# Mapping ToolId (notre enum Postgres) -> App Composio
TOOL_TO_COMPOSIO_APP: dict[str, str] = {
    "slack": App.SLACK,
    "gmail": App.GMAIL,
    "gcal": App.GOOGLECALENDAR,
    "gdrive": App.GOOGLEDRIVE,
    "notion": App.NOTION,
    "linear": App.LINEAR,
    "jira": App.JIRA,
    "github": App.GITHUB,
    "figma": App.FIGMA,
    "salesforce": App.SALESFORCE,
    "hubspot": App.HUBSPOT,
    "asana": App.ASANA,
    "whatsapp": App.WHATSAPP,
    "instagram": App.INSTAGRAM,
}

# Scopes de lecture les plus étroits proposés par chaque provider.
# Documenté explicitement (spec: "request the narrowest read scope each
# provider offers at connect time") — à ajuster une fois les apps Composio
# provisionnées, ces valeurs sont les scopes canoniques côté provider.
READ_ONLY_SCOPES: dict[str, list[str]] = {
    "slack": ["channels:read", "channels:history", "users:read"],
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly"],
    "gcal": ["https://www.googleapis.com/auth/calendar.readonly"],
    "gdrive": ["https://www.googleapis.com/auth/drive.readonly"],
    "notion": ["read_content"],
    "linear": ["read"],
    "jira": ["read:jira-work"],
    "github": ["repo:read", "read:org"],
    "figma": ["file_read"],
    "salesforce": ["api"],  # Salesforce ne granule pas plus fin par défaut ; restreindre via profil connecté
    "hubspot": ["crm.objects.contacts.read", "crm.objects.deals.read"],
    "asana": ["default"],
    "whatsapp": ["whatsapp_business_messaging"],
    "instagram": ["instagram_basic"],
}


@dataclass
class ComposioConnectionHandle:
    connected_account_id: str
    redirect_url: Optional[str]


class ComposioService:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = Composio(api_key=settings.COMPOSIO_API_KEY)
        self._settings = settings

    def entity_id(self, workspace_id: UUID) -> str:
        """Composio segmente par 'entity' — on utilise le workspace_id, ce qui
        garantit l'isolation tenant même côté Composio."""
        return f"workspace:{workspace_id}"

    async def start_authorization(self, workspace_id: UUID, tool_id: str) -> ComposioConnectionHandle:
        app = TOOL_TO_COMPOSIO_APP[tool_id]
        entity = self._client.get_entity(self.entity_id(workspace_id))
        redirect = f"{self._settings.COMPOSIO_REDIRECT_BASE_URL}/{tool_id}/callback"

        connection_request = entity.initiate_connection(
            app_name=app,
            redirect_url=redirect,
            scopes=READ_ONLY_SCOPES.get(tool_id),
        )
        return ComposioConnectionHandle(
            connected_account_id=connection_request.connectedAccountId,
            redirect_url=connection_request.redirectUrl,
        )

    async def finalize_authorization(self, workspace_id: UUID, connected_account_id: str) -> bool:
        entity = self._client.get_entity(self.entity_id(workspace_id))
        connection = entity.get_connection(connected_account_id)
        return connection.status == "ACTIVE"

    async def request_write_scope_for_outcome(
        self, workspace_id: UUID, tool_id: str, outcome_id: UUID, resources: list[str]
    ) -> str:
        """
        Grant d'écriture éphémère, lié à un outcome précis. Spec §5 : "Write
        scopes are requested per outcome ... and the grant expires with that
        outcome. Never a standing write grant."

        Implémentation : on émet un jeton Composio à portée réduite (scopes
        d'écriture) marqué avec l'outcome_id en métadonnée, et un job planifié
        le révoque à la clôture de l'outcome (delivered/failed/cancelled).
        """
        app = TOOL_TO_COMPOSIO_APP[tool_id]
        entity = self._client.get_entity(self.entity_id(workspace_id))
        write_scopes = self._write_scopes_for(tool_id)
        connection_request = entity.initiate_connection(
            app_name=app,
            scopes=write_scopes,
            metadata={"outcome_id": str(outcome_id), "resources": resources, "ttl": "outcome_bound"},
        )
        return connection_request.connectedAccountId

    def _write_scopes_for(self, tool_id: str) -> list[str]:
        write_scopes = {
            "slack": ["chat:write"],
            "gmail": ["https://www.googleapis.com/auth/gmail.send"],
            "gcal": ["https://www.googleapis.com/auth/calendar.events"],
            "notion": ["update_content"],
            "linear": ["write"],
            "jira": ["write:jira-work"],
            "salesforce": ["api"],
            "hubspot": ["crm.objects.contacts.write", "crm.objects.deals.write"],
            "asana": ["default"],
        }
        return write_scopes.get(tool_id, [])

    async def execute_read_action(
        self, workspace_id: UUID, tool_id: str, action: str, params: dict
    ) -> dict:
        """Exécute une action Composio en lecture pour un plan_step de kind='read'."""
        entity = self._client.get_entity(self.entity_id(workspace_id))
        result = entity.execute_action(action=Action(action), params=params)
        return result

    async def execute_write_action(
        self, workspace_id: UUID, connected_account_id: str, tool_id: str, action: str, params: dict
    ) -> dict:
        """
        N'est appelé QUE depuis le endpoint /approve, jamais depuis un step
        automatique. Le texte final approuvé par l'utilisateur doit être
        exactement celui envoyé ici (spec §7 : "no tool-content-derived
        instruction may bypass [the approval gate]").
        """
        entity = self._client.get_entity(self.entity_id(workspace_id))
        result = entity.execute_action(
            action=Action(action), params=params, connected_account_id=connected_account_id
        )
        return result

    async def revoke(self, workspace_id: UUID, connected_account_id: str) -> None:
        entity = self._client.get_entity(self.entity_id(workspace_id))
        entity.get_connection(connected_account_id).disable()


def get_composio_service() -> ComposioService:
    return ComposioService()