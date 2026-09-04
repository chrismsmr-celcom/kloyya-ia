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

# Expression régulière pour matcher n'importe quel sous-domaine vercel.app 
# (ex: https://kloyya-frontend.vercel.app ou https://kloyya-ia-vert.vercel.app)
VERCEL_REGEX = re.compile(r"https://.*\.vercel\.app")

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Kloyya Web App API",
        version="0.1.0",
        description="Backend sur mesure pour app.kloyya.com",
    )

    # Liste des origines autorisées avec fallback explicite
    allowed_origins = [
        getattr(settings, "FRONTEND_ORIGIN", None),  # Récupère la variable d'env ou None
        "https://kloyya-frontend.vercel.app",        # Fallback dur en cas d'oubli de la variable d'env
        VERCEL_REGEX                                 # Fallback regex pour tous les sous-domaines vercel
    ]
    
    # Filtrer les valeurs vides, None ou fausses pour éviter les erreurs de validation FastAPI
    allowed_origins = [origin for origin in allowed_origins if origin]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
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
