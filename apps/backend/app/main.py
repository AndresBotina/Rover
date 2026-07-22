"""Entrypoint de la app FastAPI de Rover.

Arranca con uvicorn apuntando a ``app.main:app``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.v1.router import TAGS_METADATA
from app.api.v1.router import router as api_v1_router
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.errors import validation_exception_handler
from app.core.logging import configure_logging

# Descripción que encabeza /docs. Corta a propósito: lo específico de cada
# dominio vive en los tags y lo de cada operación en su docstring.
_DESCRIPTION = """
API de **Rover**, el agente de viajes.

- Todo cuelga de **`/v1`**: la versión es parte de la URL desde el día uno,
  para poder evolucionar sin romper a los clientes ya publicados.
- La identidad está **delegada en Supabase Auth**: el backend no emite JWT
  propios, valida los de Supabase. Las rutas protegidas esperan el
  `access_token` en `Authorization: Bearer <token>` (botón **Authorize**).
- Los clientes propios (web y móvil) consumen la API a través del paquete
  tipado `@rover/shared`, no a mano.
"""


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

    # En producción las docs se apagan por defecto (ver Settings.docs_enabled).
    # ``openapi_url=None`` desmonta también el esquema crudo: sin él, /docs y
    # /redoc no tendrían nada que renderizar aunque quedaran montados.
    docs = settings.docs_enabled
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.version,
        description=_DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
    )
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Un único punto de montaje: el agregador ya trae el prefijo /v1.
    app.include_router(api_v1_router)
    return app


app = create_app()
