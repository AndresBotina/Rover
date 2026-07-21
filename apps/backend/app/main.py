"""Entrypoint de la app FastAPI de Rover.

Arranca con uvicorn apuntando a ``app.main:app``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.v1 import auth, health
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.errors import validation_exception_handler
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ciclo de vida de la app.

    Arranque: no se abre ninguna conexión aquí; el engine de la base es
    perezoso y se crea en el primer uso (así local/test arrancan sin DB).
    Apagado: se cierra el pool de conexiones limpiamente.
    """
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Crea y configura la instancia de FastAPI."""
    # Enruta los logs de la app a stdout antes de servir peticiones (si no,
    # los diagnósticos de los endpoints no se verían junto a los de uvicorn).
    configure_logging()
    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(health.router, prefix="/v1")
    app.include_router(auth.router, prefix="/v1")
    return app


app = create_app()
