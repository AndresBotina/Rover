"""Endpoints de autenticación, versionados bajo /v1/auth.

Delegan la identidad en Supabase Auth (app.services.auth): el backend NO
firma JWT propios (decisión de arquitectura, ver docs/backlog.md § Épica 1).
"""

import logging
import uuid
from enum import StrEnum
from typing import Self

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, model_validator
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


class RegistrationStatus(StrEnum):
    """Estado del registro. El cliente distingue los casos por ESTE campo, no
    inspeccionando si ``session`` es nula."""

    # Confirmación de email desactivada: el usuario ya tiene sesión.
    ACTIVE = "active"
    # "Confirm email" activado: usuario creado, debe confirmar su correo antes
    # de poder iniciar sesión. El cliente muestra "revisa tu correo".
    PENDING_EMAIL_CONFIRMATION = "pending_email_confirmation"


class RegisterResponse(BaseModel):
    """Cuerpo de éxito (201) de POST /v1/auth/register.

    Unión discriminada por ``status``: con ``active`` viene ``session``; con
    ``pending_email_confirmation`` NO (aún no hay sesión). El validador
    garantiza esa coherencia para que el cliente nunca reciba una combinación
    ambigua (p. ej. ``active`` sin sesión).
    """

    status: RegistrationStatus
    user: UserOut
    session: SessionOut | None = None

    @model_validator(mode="after")
    def _sesion_coherente_con_estado(self) -> Self:
        pendiente = self.status is RegistrationStatus.PENDING_EMAIL_CONFIRMATION
        if self.status is RegistrationStatus.ACTIVE and self.session is None:
            raise ValueError("un registro 'active' debe incluir la sesión")
        if pendiente and self.session is not None:
            raise ValueError("un registro pendiente de confirmación no debe traer sesión")
        return self


class LoginRequest(BaseModel):
    """Login: email + contraseña. La validación real de credenciales la hace
    Supabase; aquí solo se comprueba una forma mínima (email válido, contraseña
    presente y acotada) — sin imponer la política de longitud del registro,
    que rechazaría contraseñas válidas más cortas."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    """Cuerpo de éxito (200) de POST /v1/auth/login: usuario + sesión de Supabase."""

    user: UserOut
    session: SessionOut


# Discriminante explícito para que el cliente distinga "email sin confirmar" de
# "credenciales inválidas" sin inferir del status (mismo espíritu que HU-1.3b).
_EMAIL_NOT_CONFIRMED_REASON = "email_not_confirmed"


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> RegisterResponse:
    """Registra en Supabase Auth y crea el perfil local (best-effort, ver abajo)."""
    try:
        result = await auth_service.sign_up(payload.email, payload.password)
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

    # El perfil local se crea igual en ambos casos (con o sin sesión): el
    # usuario ya existe en Supabase apenas se registra.
    user_id = uuid.UUID(result.user_id)
    await _ensure_local_profile(user_id=user_id, email=result.email)
    user_out = UserOut(id=user_id, email=result.email)

    if result.session is None:
        # Confirmación de email pendiente: 201 SIN sesión, con estado explícito.
        return RegisterResponse(status=RegistrationStatus.PENDING_EMAIL_CONFIRMATION, user=user_out)
    return RegisterResponse(
        status=RegistrationStatus.ACTIVE,
        user=user_out,
        session=SessionOut(
            access_token=result.session.access_token,
            refresh_token=result.session.refresh_token,
        ),
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    """Inicia sesión delegando en Supabase Auth; devuelve usuario + sesión.

    A diferencia del registro, el login NO crea ni materializa el perfil
    local: si un usuario puede autenticarse pero aún no tiene perfil, su
    creación perezosa es responsabilidad del middleware de la HU-1.6 —el punto
    por el que pasa TODA petición autenticada—. Duplicar esa lógica aquí la
    pondría en dos sitios.
    """
    try:
        result = await auth_service.sign_in(payload.email, payload.password)
    except auth_service.InvalidCredentials as exc:
        _log_provider_failure(logging.WARNING, "credenciales inválidas", exc)
        # Mismo mensaje para email inexistente y contraseña incorrecta: no se
        # revela si la cuenta existe (evita enumerar cuentas).
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Email o contraseña incorrectos."
        ) from exc
    except auth_service.EmailNotConfirmed as exc:
        _log_provider_failure(logging.WARNING, "email sin confirmar", exc)
        # 403, no 401: las credenciales SON correctas; lo que falta es confirmar
        # el correo. El cuerpo lleva un discriminante explícito para que el
        # cliente muestre "confirma tu correo" sin inferir del status.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "reason": _EMAIL_NOT_CONFIRMED_REASON,
                "message": "Debes confirmar tu correo antes de iniciar sesión.",
            },
        ) from exc
    except auth_service.RateLimited as exc:
        _log_provider_failure(logging.WARNING, "límite de tasa", exc)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiados intentos; prueba de nuevo en unos minutos.",
        ) from exc
    except auth_service.AuthProviderError as exc:
        _log_provider_failure(logging.ERROR, "fallo del proveedor", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No se pudo iniciar sesión; intenta de nuevo en unos minutos.",
        ) from exc

    return LoginResponse(
        user=UserOut(id=uuid.UUID(result.user_id), email=result.email),
        session=SessionOut(
            access_token=result.session.access_token,
            refresh_token=result.session.refresh_token,
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
