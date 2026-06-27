"""Endpoint de salud, versionado bajo /v1."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Cuerpo tipado de la respuesta del healthcheck."""

    status: Literal["ok"]
    version: str
    env: str


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Reporta que el servicio está vivo y su versión/entorno."""
    return HealthResponse(status="ok", version=settings.version, env=settings.env)
