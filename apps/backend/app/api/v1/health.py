"""Endpoints de salud, versionados bajo /v1."""

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import ApiError, ErrorCode, error_doc

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Cuerpo tipado de la respuesta del healthcheck."""

    status: Literal["ok"]
    version: str
    env: str


class DbHealthResponse(BaseModel):
    """Conectividad con la base de datos: solo la forma del CASO SANO.

    El fallo NO se reporta aquí con un ``status: "error"``: desde la HU-1.8 un
    503 sale con el formato único de error, como cualquier otro error de la
    API. Así el cliente parsea todos los fallos igual (un solo type guard) en
    vez de tener un caso especial para la sonda.
    """

    status: Literal["ok"]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Estado del servicio",
    responses={200: {"description": "El servicio está vivo; devuelve versión y ambiente."}},
)
def get_health() -> HealthResponse:
    """Sonda de vida del proceso: **no** toca la base ni servicios externos.

    Es el `healthCheckPath` del Blueprint de Render: un deploy solo se marca
    sano si esto responde 200.
    """
    return HealthResponse(status="ok", version=settings.version, env=settings.env)


@router.get(
    "/health/db",
    response_model=DbHealthResponse,
    summary="Conectividad con la base de datos",
    responses={
        200: {"description": "La base respondió al `SELECT 1`."},
        503: error_doc(
            "`service_unavailable` — no se pudo conectar. El mensaje es "
            "genérico a propósito: la causa real (la URL o el error del driver) "
            "puede contener credenciales."
        ),
    },
)
async def get_db_health() -> DbHealthResponse:
    """Verifica la conexión a la base con un ``SELECT 1`` async.

    Itera ``get_db`` directamente (el mismo camino que usará cualquier
    endpoint) en vez de inyectarlo con Depends: así una config ausente o una
    base caída se reportan como 503 tipado y NUNCA se filtra la causa real al
    cliente (la URL o el error del driver pueden contener credenciales).
    """
    try:
        async for session in get_db():
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.SERVICE_UNAVAILABLE,
            "No se pudo conectar a la base de datos.",
        ) from exc
    return DbHealthResponse(status="ok")
