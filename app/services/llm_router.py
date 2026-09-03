"""
Routeur LLM multi-fournisseurs.

Un seul point d'entrée pour tout le moteur (clarify, plan, reason, answer,
embeddings). Utilise LiteLLM comme couche d'abstraction : chaque modèle est
adressé sous la forme "provider/model", ex:

    anthropic/claude-sonnet-4-6
    anthropic/claude-opus-4-1
    openai/gpt-4o
    openai/gpt-4o-mini
    perplexity/sonar-pro          -> pour les steps 'read'/'reason' qui bénéficient
                                       d'une recherche web native
    deepseek/deepseek-chat
    deepseek/deepseek-reasoner
    moonshot/moonshot-v1-128k     -> Kimi / Moonshot AI
    gemini/gemini-2.0-flash

LiteLLM lit les clés API depuis les variables d'environnement standard de
chaque fournisseur ; on les propage depuis Settings au démarrage.

Pourquoi un routeur et pas un provider fixe : la spec (§7) dit explicitement
"not prescribing a stack" mais impose des contraintes de calibration de
confiance, de citations et de budget — donc le routeur porte ces garde-fous
une fois pour tous les fournisseurs plutôt que de les dupliquer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

litellm.drop_params = True  # tolère des kwargs non supportés par un provider donné
litellm.suppress_debug_info = True


class TaskRole(str, Enum):
    CLARIFY = "clarify"          # une question, avec options concrètes
    PLAN = "plan"                # génération des plan_steps
    REASON = "reason"            # le "pushback step" (spec §7)
    ANSWER = "answer"            # synthèse finale + confidence
    RESEARCH = "research"        # lecture augmentée par recherche web (Perplexity brille ici)
    FAST = "fast"                # petites tâches (titres, résumés courts)
    EMBEDDING = "embedding"


def _bootstrap_provider_keys() -> None:
    settings = get_settings()
    mapping = {
        "OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY,
        "PERPLEXITYAI_API_KEY": settings.PERPLEXITY_API_KEY,
        "DEEPSEEK_API_KEY": settings.DEEPSEEK_API_KEY,
        "MOONSHOT_API_KEY": settings.MOONSHOT_API_KEY,
        "GEMINI_API_KEY": settings.GEMINI_API_KEY,
        "GROQ_API_KEY": settings.GROQ_API_KEY,
    }
    for env_key, value in mapping.items():
        if value:
            os.environ[env_key] = value


_bootstrap_provider_keys()


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    raw: Any = field(repr=False, default=None)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMRouter:
    """
    Résout quel modèle utiliser pour un rôle donné, avec :
      1. la préférence explicite du workspace (`workspaces.llm_provider_prefs`)
      2. le défaut global défini dans Settings
    et expose des helpers haut niveau (complete, embed) avec retry.
    """

    def __init__(self, workspace_prefs: Optional[dict] = None) -> None:
        self.settings = get_settings()
        self.workspace_prefs = workspace_prefs or {}

    def resolve_model(self, role: TaskRole) -> str:
        if role.value in self.workspace_prefs:
            return self.workspace_prefs[role.value]

        defaults = {
            TaskRole.CLARIFY: self.settings.DEFAULT_FAST_MODEL,
            TaskRole.PLAN: self.settings.DEFAULT_PLANNER_MODEL,
            TaskRole.REASON: self.settings.DEFAULT_REASONING_MODEL,
            TaskRole.ANSWER: self.settings.DEFAULT_REASONING_MODEL,
            TaskRole.RESEARCH: self.settings.DEFAULT_RESEARCH_MODEL,
            TaskRole.FAST: self.settings.DEFAULT_FAST_MODEL,
            TaskRole.EMBEDDING: self.settings.DEFAULT_EMBEDDING_MODEL,
        }
        return defaults[role]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def complete(
        self,
        role: TaskRole,
        messages: list[dict],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        response_format: Optional[dict] = None,
        override_model: Optional[str] = None,
    ) -> LLMResult:
        model = override_model or self.resolve_model(role)
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if response_format:
            kwargs["response_format"] = response_format

        resp = await litellm.acompletion(**kwargs)
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResult(
            text=choice.message.content or "",
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            raw=resp,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def embed(self, texts: list[str], *, override_model: Optional[str] = None) -> list[list[float]]:
        model = override_model or self.resolve_model(TaskRole.EMBEDDING)
        resp = await litellm.aembedding(model=model, input=texts)
        return [item["embedding"] for item in resp["data"]]


def get_llm_router(workspace_prefs: Optional[dict] = None) -> LLMRouter:
    return LLMRouter(workspace_prefs=workspace_prefs)