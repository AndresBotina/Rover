"""Endpoints de perfil de usuario (``/v1/users/me``), protegidos por el middleware.

Organización por DOMINIO: el router ``users`` va aparte del de ``auth``,
adelantando parte de la HU-1.9 (estructura de la API por dominio). Reconciliar
allí.

El id del usuario SIEMPRE sale del token (``get_current_user``), nunca del
cuerpo ni de la URL: por eso la ruta es ``/me`` y no ``/users/{id}``.
"""

import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.core.database import get_db
from app.models import Plan, UserProfile

router = APIRouter(prefix="/users", tags=["users"])

# Tope del objeto ``preferences`` (JSON serializado). Es un JSONB de forma
# libre; sin límite, alguien podría almacenar payloads enormes en cada fila.
# Se acota el RESULTADO del merge (lo que se guarda), no solo lo entrante, para
# que la acumulación entre PATCHes tampoco crezca sin control. 8 KB es holgado
# para preferencias de viaje (pares clave-valor).
_MAX_PREFERENCES_BYTES = 8192


class ProfileResponse(BaseModel):
    """Perfil completo del usuario autenticado."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    plan: Plan
    preferences: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProfileUpdateRequest(BaseModel):
    """Cuerpo del PATCH: SOLO ``preferences`` es editable.

    ``extra='forbid'``: un intento de tocar ``plan``, ``id`` o ``email`` (o
    cualquier otro campo) responde 422 en vez de ignorarse en silencio.
    Exponer campos de más en un PATCH es un fallo de seguridad clásico: si el
    usuario pudiera escribir ``plan`` se ascendería solo a un plan de pago
    (escalada de privilegios). ``plan``, ``id`` y ``email`` los gobiernan
    Supabase (identidad) y la monetización (Épica 5), nunca el cliente.
    """

    model_config = ConfigDict(extra="forbid")

    # ``dict[str, Any]`` obliga a que sea un OBJETO JSON: un array, número o
    # string en ``preferences`` se rechaza con 422 por tipo.
    preferences: dict[str, Any]


async def _cargar_perfil(db: AsyncSession, user_id: uuid.UUID) -> UserProfile:
    """Carga el perfil del usuario; get_current_user garantiza que ya existe."""
    profile = await db.get(UserProfile, user_id)
    if profile is None:  # pragma: no cover - get_current_user ya lo materializa
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Perfil no encontrado.")
    return profile


@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileResponse:
    """Devuelve el perfil completo del usuario del token."""
    profile = await _cargar_perfil(db, user.id)
    return ProfileResponse.model_validate(profile)


@router.patch("/me", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileResponse:
    """Actualiza SOLO ``preferences`` (merge superficial) y devuelve el perfil.

    Semántica: **merge superficial** de claves de primer nivel
    (``{**actuales, **entrantes}``), NO reemplazo total. Razón: web y móvil
    envían actualizaciones PARCIALES; con reemplazo tendrían que
    leer-modificar-escribir el objeto entero (y dos clientes se pisarían). Con
    merge, una clave no mencionada se conserva. Es predecible: las claves de
    primer nivel enviadas se fijan, y los objetos anidados se reemplazan en su
    clave (no hay merge profundo), lo que evita ambigüedad.
    """
    profile = await _cargar_perfil(db, user.id)

    merged = {**profile.preferences, **payload.preferences}
    if len(json.dumps(merged).encode("utf-8")) > _MAX_PREFERENCES_BYTES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"preferences supera el máximo de {_MAX_PREFERENCES_BYTES} bytes.",
        )

    # Asignación (no mutación in-place): así SQLAlchemy marca la columna sucia y
    # dispara la UPDATE (con onupdate=now() en updated_at).
    profile.preferences = merged
    await db.commit()
    await db.refresh(profile)  # recarga updated_at (lo pone la base)
    return ProfileResponse.model_validate(profile)
