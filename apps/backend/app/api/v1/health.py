"""Endpoints de salud, versionados bajo /v1."""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Cuerpo tipado de la respuesta del healthcheck."""

    status: Literal["ok"]
    version: str
    env: str


class DbHealthResponse(BaseModel):
    """Estado de la conectividad con la base de datos."""

    status: Literal["ok", "error"]
    detail: str | None = None


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Reporta que el servicio está vivo y su versión/entorno."""
    return HealthResponse(status="ok", version=settings.version, env=settings.env)


@router.get("/health/db", response_model=DbHealthResponse)
async def get_db_health(response: Response) -> DbHealthResponse:
    """Verifica la conexión a la base con un ``SELECT 1`` async.

    Itera ``get_db`` directamente (el mismo camino que usará cualquier
    endpoint) en vez de inyectarlo con Depends: así una config ausente o una
    base caída se reportan como 503 tipado y NUNCA se filtra la causa real al
    cliente (la URL o el error del driver pueden contener credenciales).
    """
    try:
        async for session in get_db():
            await session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DbHealthResponse(status="error", detail="No se pudo conectar a la base de datos.")
    return DbHealthResponse(status="ok", detail=None)
