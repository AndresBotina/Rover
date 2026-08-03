"""Endpoints de autenticación, versionados bajo /v1/auth (el prefijo lo pone
el agregador ``app.api.v1.router``).

Delegan la identidad en Supabase Auth (app.services.auth): el backend NO
firma JWT propios (decisión de arquitectura, ver docs/backlog.md § Épica 1).
"""

import logging
import uuid
from enum import StrEnum
from typing import Self

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.errors import ApiError, ErrorCode, error_doc
from app.models import UserProfile
from app.services import auth as auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """Alta de usuario: email + contraseña. La política fuerte la aplica Supabase."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "ana@example.com", "password": "un-secreto-largo"}]
        }
    )

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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "active",
                    "user": {
                        "id": "0f6c2f9e-1f2a-4c3b-9d5e-8a7b6c5d4e3f",
                        "email": "ana@example.com",
                    },
                    "session": {
                        "access_token": "eyJhbGciOiJFUzI1NiIs…",
                        "refresh_token": "v1.MRq8…",
                        "token_type": "bearer",
                    },
                },
                {
                    "status": "pending_email_confirmation",
                    "user": {
                        "id": "0f6c2f9e-1f2a-4c3b-9d5e-8a7b6c5d4e3f",
                        "email": "ana@example.com",
                    },
                    "session": None,
                },
            ]
        }
    )

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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "ana@example.com", "password": "un-secreto-largo"}]
        }
    )

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    """Cuerpo de éxito (200) de POST /v1/auth/login: usuario + sesión de Supabase."""

    user: UserOut
    session: SessionOut


# NOTA (HU-1.8): el discriminante que distingue "email sin confirmar" de
# "credenciales inválidas" ya no es un campo `reason` dentro del `detail`: es el
# `code` del formato único de error (`email_not_confirmed`), que TODOS los
# errores traen. El contrato no cambia de fondo —el cliente sigue sin inferir
# nada del status—, cambia de sitio: deja de ser un caso especial.


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un usuario",
    responses={
        201: {
            "description": (
                "Usuario creado. Con sesión (`active`) o sin ella si Supabase "
                "exige confirmar el correo (`pending_email_confirmation`)."
            )
        },
        409: error_doc("`email_already_exists` — ya existe una cuenta con ese email."),
        422: error_doc(
            "`validation_error` (forma del cuerpo), `weak_password` o "
            "`invalid_email` (rechazo de la política de Supabase)."
        ),
        429: error_doc(
            "`rate_limited` — demasiados intentos. Mismo código tanto si el "
            "límite es el de la API (HU-1.7, con `Retry-After`) como si lo "
            "impuso el proveedor de identidad: la acción del cliente es la "
            "misma y el catálogo de códigos es de dominio, no de origen."
        ),
        503: error_doc("`service_unavailable` — Supabase Auth no respondió o falló."),
    },
)
async def register(payload: RegisterRequest) -> RegisterResponse:
    """Da de alta al usuario en **Supabase Auth** y crea su perfil local.

    La respuesta es una **unión discriminada por `status`**, no un booleano:

    - **`active`** — la confirmación de email está desactivada: el usuario ya
      viene con `session` (access + refresh token) y puede llamar a las rutas
      protegidas.
    - **`pending_email_confirmation`** — hay que confirmar el correo: `session`
      es `null` y el cliente debe mostrar "revisa tu correo".

    El perfil local se crea de forma idempotente y su fallo **no** rompe el
    registro: si no se consigue, lo materializa el middleware en el primer
    acceso autenticado.
    """
    try:
        result = await auth_service.sign_up(payload.email, payload.password)
    except auth_service.RateLimited as exc:
        _log_provider_failure(logging.WARNING, "límite de tasa", exc)
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ErrorCode.RATE_LIMITED,
            "Demasiados intentos; prueba de nuevo en unos minutos.",
        ) from exc
    except auth_service.EmailAlreadyExists as exc:
        _log_provider_failure(logging.WARNING, "email ya registrado", exc)
        # Mensaje genérico: no confirma NI desmiente más de lo estrictamente
        # necesario (evita que un atacante use /register para enumerar emails).
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.EMAIL_ALREADY_EXISTS,
            "Ya existe una cuenta con ese email.",
        ) from exc
    except (auth_service.WeakPassword, auth_service.InvalidEmail) as exc:
        _log_provider_failure(logging.WARNING, "datos rechazados por el proveedor", exc)
        # El mensaje del proveedor SÍ se muestra (explica qué falta en la
        # contraseña); su error_code crudo NO: se traduce al código de dominio.
        codigo = (
            ErrorCode.WEAK_PASSWORD
            if isinstance(exc, auth_service.WeakPassword)
            else ErrorCode.INVALID_EMAIL
        )
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, codigo, str(exc)) from exc
    except auth_service.AuthProviderError as exc:
        _log_provider_failure(logging.ERROR, "fallo del proveedor", exc)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.SERVICE_UNAVAILABLE,
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


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Iniciar sesión",
    responses={
        200: {"description": "Credenciales correctas: usuario y sesión de Supabase."},
        401: error_doc(
            "`invalid_credentials` — email o contraseña incorrectos. El cuerpo "
            "es **idéntico** en ambos casos: no se revela si la cuenta existe."
        ),
        403: error_doc(
            "`email_not_confirmed` — las credenciales son correctas, pero falta "
            "confirmar el correo. El propio `code` es el discriminante."
        ),
        # Declarado a mano para sustituir el 422 automático de FastAPI, cuyo
        # esquema (HTTPValidationError) ya no es el que devuelve la API.
        422: error_doc("`validation_error` — el cuerpo no tiene la forma esperada."),
        429: error_doc(
            "`rate_limited` — demasiados intentos. Este endpoint tiene un "
            "límite MÁS ESTRICTO que el resto de la API (HU-1.7): es donde se "
            "adivinan contraseñas. La cabecera `Retry-After` dice en cuántos "
            "segundos reintentar."
        ),
        503: error_doc("`service_unavailable` — Supabase Auth no respondió o falló."),
    },
)
async def login(payload: LoginRequest) -> LoginResponse:
    """Valida las credenciales contra **Supabase Auth** y devuelve la sesión.

    El `access_token` de la sesión es el que viaja en
    `Authorization: Bearer <token>` hacia las rutas protegidas.

    A diferencia del registro, el login **no** crea ni materializa el perfil
    local: si un usuario puede autenticarse pero aún no tiene perfil, su
    creación perezosa es responsabilidad del middleware (`get_current_user`),
    el punto por el que pasa TODA petición autenticada. Duplicar esa lógica
    aquí la pondría en dos sitios.
    """
    try:
        result = await auth_service.sign_in(payload.email, payload.password)
    except auth_service.InvalidCredentials as exc:
        _log_provider_failure(logging.WARNING, "credenciales inválidas", exc)
        # Mismo mensaje para email inexistente y contraseña incorrecta: no se
        # revela si la cuenta existe (evita enumerar cuentas).
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.INVALID_CREDENTIALS,
            "Email o contraseña incorrectos.",
        ) from exc
    except auth_service.EmailNotConfirmed as exc:
        _log_provider_failure(logging.WARNING, "email sin confirmar", exc)
        # 403, no 401: las credenciales SON correctas; lo que falta es confirmar
        # el correo. El cuerpo lleva un discriminante explícito para que el
        # cliente muestre "confirma tu correo" sin inferir del status.
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.EMAIL_NOT_CONFIRMED,
            "Debes confirmar tu correo antes de iniciar sesión.",
        ) from exc
    except auth_service.RateLimited as exc:
        _log_provider_failure(logging.WARNING, "límite de tasa", exc)
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ErrorCode.RATE_LIMITED,
            "Demasiados intentos; prueba de nuevo en unos minutos.",
        ) from exc
    except auth_service.AuthProviderError as exc:
        _log_provider_failure(logging.ERROR, "fallo del proveedor", exc)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.SERVICE_UNAVAILABLE,
            "No se pudo iniciar sesión; intenta de nuevo en unos minutos.",
        ) from exc

    return LoginResponse(
        user=UserOut(id=uuid.UUID(result.user_id), email=result.email),
        session=SessionOut(
            access_token=result.session.access_token,
            refresh_token=result.session.refresh_token,
        ),
    )


# NOTA (HU-1.9): aquí vivía `GET /v1/auth/me`, la ruta con la que se verificó
# el middleware antes de que existieran los endpoints de perfil. Devolvía
# (id, email, plan): un SUBCONJUNTO estricto de `GET /v1/users/me`, obtenido
# con exactamente el mismo trabajo (validar el token + leer la fila del
# perfil). Se retiró al consolidar: dos rutas que responden "quién soy" con el
# mismo costo son dos contratos que mantener y una duda para el cliente.
# `GET /v1/users/me` es ahora el único endpoint de identidad/perfil.


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
