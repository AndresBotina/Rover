"""Entrypoint de la app FastAPI de Rover.

Arranca con uvicorn apuntando a ``app.main:app``.
"""

from fastapi import FastAPI

from app.api.v1 import health
from app.core.config import settings


def create_app() -> FastAPI:
    """Crea y configura la instancia de FastAPI."""
    app = FastAPI(title=settings.app_name, version=settings.version)
    app.include_router(health.router, prefix="/v1")
    return app


app = create_app()
