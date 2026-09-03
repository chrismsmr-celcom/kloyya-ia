from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CreateOutcomeRequest(BaseModel):
    title: str
    scope: Optional[dict] = None


class ClarifyRequest(BaseModel):
    answer: str


class PlanStepUpdate(BaseModel):
    id: UUID
    title: Optional[str] = None
    detail: Optional[str] = None
    state: Optional[str] = None  # ex: 'skipped' pour supprimer une étape


class UpdatePlanRequest(BaseModel):
    steps: list[PlanStepUpdate]


class FindingResponseRequest(BaseModel):
    response: str  # 'pivot' | 'note'


class ApproveRequest(BaseModel):
    artifact_ids: list[UUID] = Field(alias="artifactIds")

    class Config:
        populate_by_name = True


class OutcomeOut(BaseModel):
    id: UUID
    title: str
    state: str
    created_at: datetime
    started_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    sources_revoked: bool = False


class ConnectionScopesUpdate(BaseModel):
    resources: list[str]


class OnboardingRequest(BaseModel):
    persona: str
    role: str
    first_outcome: str = Field(alias="firstOutcome")
    requested_tools: list[str] = Field(alias="requestedTools")

    class Config:
        populate_by_name = True