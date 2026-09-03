"""
Configuration centralisée. Tout vient de l'environnement (.env en local,
variables d'environnement réelles en prod). Rien n'est codé en dur ici.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    ENV: str = "development"
    APP_NAME: str = "kloyya-webapp-api"
    API_BASE_URL: str = "http://localhost:8000"
    FRONTEND_ORIGIN: str = "http://localhost:5500"  # là où tourne Kloyya-prototype.html / index.html
    LOG_LEVEL: str = "INFO"

    # --- Supabase (auth + Postgres + storage) ---
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str  # pour vérifier les JWT émis par Supabase Auth
    DATABASE_URL: str  # postgres://... (connexion directe Postgres, pooler Supabase recommandé)

    # --- Composio (auth des outils / tool connections) ---
    COMPOSIO_API_KEY: str
    COMPOSIO_REDIRECT_BASE_URL: str = "http://localhost:8000/api/connections"

    # --- LLM providers (multi-provider router via LiteLLM) ---
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    PERPLEXITY_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    MOONSHOT_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None

    DEFAULT_PLANNER_MODEL: str = "anthropic/claude-sonnet-4-6"
    DEFAULT_REASONING_MODEL: str = "anthropic/claude-opus-4-1"
    DEFAULT_FAST_MODEL: str = "openai/gpt-4o-mini"
    DEFAULT_RESEARCH_MODEL: str = "perplexity/sonar-pro"
    DEFAULT_EMBEDDING_MODEL: str = "openai/text-embedding-3-large"

    # --- RAG ---
    RAG_CHUNK_SIZE: int = 1200
    RAG_CHUNK_OVERLAP: int = 150
    RAG_TOP_K: int = 8
    RAG_MIN_SIMILARITY: float = 0.72
    DOCUMENT_STORAGE_BUCKET: str = "workspace-documents"

    # --- Patchright (browser automation pour les lectures sans API propre) ---
    PATCHRIGHT_HEADLESS: bool = True
    PATCHRIGHT_TIMEOUT_MS: int = 45000

    # --- Run engine ---
    REDIS_URL: str = "redis://localhost:6379/0"
    RUN_WALL_CLOCK_CAP_SECONDS: int = 1200  # 20 min, cf. spec §7
    RUN_TOKEN_BUDGET: int = 400_000
    RUN_CONCURRENCY_PER_WORKSPACE: int = 2

    # --- Billing (service landing, partagé ici pour les entitlements) ---
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    # --- Transcription (voice input, spec webapp §9) ---
    TRANSCRIPTION_PROVIDER: str = "openai"  # openai (whisper) par défaut


@lru_cache
def get_settings() -> Settings:
    return Settings()