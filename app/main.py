import structlog
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.session import init_pool, close_pool
from app.routers import (
    billing, connections, documents, impact, memory, onboarding, outcomes
)

log = structlog.get_logger()

# Regex pour accepter n'importe quel sous-domaine vercel.app
VERCEL_REGEX = re.compile(r"https://.*\.vercel\.app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialisation du pool de base de données au démarrage
    await init_pool()
    yield
    # Nettoyage à l'arrêt
    await close_pool()

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Kloyya Web App API",
        version="0.1.0",
        description="Backend sur mesure pour app.kloyya.com",
        lifespan=lifespan,
    )

    # Liste sécurisée des origines autorisées
    allowed_origins = [
        getattr(settings, "FRONTEND_ORIGIN", None),
        "https://kloyya-frontend.vercel.app",
        VERCEL_REGEX
    ]
    # Filtre les valeurs None ou vides
    allowed_origins = [origin for origin in allowed_origins if origin]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Last-Event-ID"],
    )

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
