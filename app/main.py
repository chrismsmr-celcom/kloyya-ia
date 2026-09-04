from contextlib import asynccontextmanager
import structlog
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db.session import init_pool, close_pool
from app.routers import (
    billing, connections, documents, impact, memory, onboarding, outcomes
)

log = structlog.get_logger()

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Kloyya Web App API",
        version="0.1.0",
        description="Backend sur mesure pour app.kloyya.com",
    )
    
    # ✅ CORS Configuration - FIXED
    app.add_middleware(
        CORSMiddleware,
        # Origines spécifiques
        allow_origins=[
            "https://kloyya-frontend.vercel.app",    # Production
            "http://localhost:3000",                  # Dev local frontend
            "http://localhost:3001",                  # Dev local backend (tests)
        ],
        # Ou utilise allow_origin_regex pour matcher les patterns
        allow_origin_regex=r"https://.*\.vercel\.app",  # ← Accepte tous les *.vercel.app
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Last-Event-ID"],
    )
    
    # Include all routers
    app.include_router(outcomes.router)
    app.include_router(connections.router)
    app.include_router(memory.router)
    app.include_router(impact.router)
    app.include_router(documents.router)
    app.include_router(onboarding.router)
    app.include_router(billing.router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "env": settings.ENV}

    return app

app = create_app()
