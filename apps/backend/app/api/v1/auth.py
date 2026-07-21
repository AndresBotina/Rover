"""Endpoints de autenticación, versionados bajo /v1/auth.

Delegan la identidad en Supabase Auth (app.services.auth): el backend NO
firma JWT propios (decisión de arquitectura, ver docs/backlog.md § Épica 1).
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.models import UserProfile
from app.services import auth as auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """Alta de usuario: email + contraseña. La política fuerte la aplica Supabase."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """Datos mínimos del usuario. NUNCA la contraseña ni más de lo necesario."""

    id: uuid.UUID
    email: str


class SessionOut(BaseModel):
    """Sesión de Supabase: son SUS tokens, el backend no firma JWT propios."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    """Cuerpo de éxito de POST /v1/auth/register."""

    user: UserOut
    session: SessionOut


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> RegisterResponse:
    """Registra en Supabase Auth y crea el perfil local (best-effort, ver abajo)."""
    try:
        supabase_session = await auth_service.sign_up(payload.email, payload.password)
    except auth_service.RateLimited as exc:
        _log_provider_failure(logging.WARNING, "límite de tasa", exc)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiados intentos; prueba de nuevo en unos minutos.",
        ) from exc
    except auth_service.EmailAlreadyExists as exc:
        _log_provider_failure(logging.WARNING, "email ya registrado", exc)
        # Mensaje genérico: no confirma NI desmiente más de lo estrictamente
        # necesario (evita que un atacante use /register para enumerar emails).
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese email."
        ) from exc
    except (auth_service.WeakPassword, auth_service.InvalidEmail) as exc:
        _log_provider_failure(logging.WARNING, "datos rechazados por el proveedor", exc)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except auth_service.AuthProviderError as exc:
        _log_provider_failure(logging.ERROR, "fallo del proveedor", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No se pudo completar el registro; intenta de nuevo en unos minutos.",
        ) from exc

    user_id = uuid.UUID(supabase_session.user_id)
    await _ensure_local_profile(user_id=user_id, email=supabase_session.email)

    return RegisterResponse(
        user=UserOut(id=user_id, email=supabase_session.email),
        session=SessionOut(
            access_token=supabase_session.access_token,
            refresh_token=supabase_session.refresh_token,
        ),
    )


def _log_provider_failure(level: int, contexto: str, exc: auth_service.AuthError) -> None:
    """Deja rastro de la causa REAL del fallo en los logs del servidor.

    Registra SOLO el diagnóstico del proveedor (status, error_code y su
    mensaje): la respuesta al cliente sigue siendo genérica, pero al depurar
    la causa es visible. NUNCA la contraseña ni las llaves — no viven en la
    excepción, así que no pueden colarse aquí.
    """
    logger.log(
        level,
        "Registro rechazado (%s): status=%s error_code=%s provider_msg=%s",
        contexto,
        exc.provider_status,
        exc.provider_error_code,
        exc.provider_message,
    )


async def _ensure_local_profile(*, user_id: uuid.UUID, email: str) -> None:
    """Crea el perfil local si falta; NUNCA rompe el registro si algo sale mal.

    Gestiona su PROPIA sesión (itera ``get_db()`` a mano, sin ``Depends``):
    así un fallo de la dependencia de base de datos (config ausente, conexión
    caída) queda contenido aquí igual que un fallo al hacer commit — mismo
    patrón que ``get_db_health`` en health.py. En este punto el usuario YA
    existe en Supabase; no hay compensación (no se borra de Supabase). El
    perfil se crea de forma perezosa en el primer acceso autenticado (HU-1.6)
    si esta llamada no lo consigue.
    """
    try:
        async for session in get_db():
            session.add(UserProfile(id=user_id, email=email))
            try:
                await session.commit()
            except IntegrityError:
                # El id ya tiene perfil: comportamiento idempotente esperado,
                # no un fallo (puede pasar si esta función se reintenta).
                await session.rollback()
    except Exception:
        logger.exception(
            "No se pudo crear el perfil local para el usuario %s; se creará "
            "de forma perezosa en el primer acceso autenticado.",
            user_id,
        )
