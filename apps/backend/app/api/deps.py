"""Dependencias de FastAPI compartidas por los endpoints.

``get_current_user`` es el middleware de autenticación: valida el JWT de
Supabase, resuelve el PERFIL LOCAL del usuario y —punto ÚNICO de
materialización— lo crea de forma perezosa e idempotente si aún no existe.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.database import get_db
from app.core.security import JWKSUnavailable, TokenError, validate_access_token
from app.models import Plan, UserProfile

logger = logging.getLogger(__name__)

# Esquema de seguridad SOLO para la documentación (HU-1.9): declararlo hace que
# OpenAPI marque las rutas protegidas como tales y que /docs muestre el botón
# "Authorize" para mandar el token. NO valida nada: el token lo sigue leyendo y
# verificando este módulo.
#
# Por qué no se usa su valor de retorno para extraer el token:
#   - con ``auto_error=True`` la librería respondería 403 con SU propio cuerpo
#     cuando falta el header, saltándose el 401 uniforme y el log de esta capa;
#   - con ``auto_error=False`` devuelve ``None`` tanto si no hay header como si
#     el esquema no es Bearer, y perderíamos el motivo preciso en el log
#     (``missing_authorization_header`` vs ``invalid_scheme``).
# El header crudo se lee del Request y lo parsea ``_extract_bearer``.
bearer_scheme = HTTPBearer(
    scheme_name="SupabaseAccessToken",
    description="Access token de Supabase (`session.access_token` de /v1/auth/login).",
    auto_error=False,
)

# Cuerpo y cabecera UNIFORMES para cualquier fallo de autenticación: no se
# revela el motivo (expirado, firma, usuario inexistente…). El motivo real va
# al log del servidor.
_UNAUTHORIZED_DETAIL = "No autenticado."
_SERVICE_UNAVAILABLE_DETAIL = "Servicio no disponible temporalmente."


# Respuestas comunes a TODA ruta protegida, para documentarlas sin repetirlas
# en cada endpoint. Describen el CUÁNDO, nunca el motivo concreto del rechazo:
# el cuerpo del 401 es uniforme a propósito y la documentación no debe sugerir
# lo contrario.
AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "description": (
            "Falta el token, o no es válido (formato, firma, expiración, "
            "issuer o audiencia). El cuerpo es **uniforme** para todos los "
            "motivos; el motivo real solo va al log del servidor."
        )
    },
    503: {
        "description": (
            "Fallo de infraestructura propia (el JWKS de Supabase o la base de "
            "datos no están disponibles). No implica que el token sea inválido."
        )
    },
}


@dataclass(frozen=True)
class CurrentUser:
    """Identidad resuelta del request: disponible para los endpoints protegidos."""

    id: uuid.UUID
    email: str
    plan: Plan


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        _UNAUTHORIZED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_bearer(authorization: str | None) -> str:
    """Saca el token del header ``Authorization: Bearer <token>`` o lanza TokenError."""
    if authorization is None:
        raise TokenError("missing_authorization_header")
    partes = authorization.split(maxsplit=1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        raise TokenError("invalid_scheme")
    token = partes[1].strip()
    if not token:
        raise TokenError("empty_token")
    return token


def _identity_from_claims(claims: dict[str, object]) -> tuple[uuid.UUID, str]:
    """Extrae ``(user_id, email)`` de los claims ya validados."""
    sub = claims.get("sub")
    email = claims.get("email")
    if not isinstance(sub, str):
        raise TokenError("missing_sub")
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise TokenError("invalid_sub") from exc
    if not isinstance(email, str) or not email:
        # El perfil local necesita email (NOT NULL); sin él no se puede
        # materializar. Los access tokens de Supabase siempre lo traen.
        raise TokenError("missing_email")
    return user_id, email


async def _resolve_or_create_profile(*, user_id: uuid.UUID, email: str) -> UserProfile:
    """Devuelve el perfil local del usuario, creándolo si no existe.

    ESTE es el único lugar responsable de materializar el perfil (lo que el
    registro y el login posponen): un usuario que se registró pero cuyo perfil
    falló, o creado directamente en Supabase, obtiene aquí su fila. Idempotente
    y con manejo de carrera: si dos peticiones simultáneas del mismo usuario
    nuevo compiten, el ``IntegrityError`` del segundo se resuelve releyendo la
    fila que creó el primero.
    """
    async for session in get_db():
        existing = await session.get(UserProfile, user_id)
        if existing is not None:
            return existing

        profile = UserProfile(id=user_id, email=email)
        session.add(profile)
        try:
            await session.commit()
        except IntegrityError:
            # Otra petición creó el perfil entre el get y el commit: no es un
            # error, es la carrera esperada. Se relee la fila existente.
            await session.rollback()
            existing = await session.get(UserProfile, user_id)
            if existing is None:
                raise  # IntegrityError por otra causa: que suba.
            return existing
        return profile

    raise RuntimeError("get_db no entregó una sesión")  # pragma: no cover


async def get_current_user(
    request: Request,
    # Dependencia declarativa: su único efecto es documentar el esquema Bearer
    # en OpenAPI (ver ``bearer_scheme``). Su valor se ignora a propósito.
    _scheme: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> CurrentUser:
    """Valida el JWT de Supabase y resuelve (o crea) el perfil local del usuario.

    Cualquier fallo de autenticación → 401 UNIFORME (mismo cuerpo para todos
    los motivos); el motivo real se registra en el log. Un problema de infra
    (JWKS o base de datos no disponibles) → 503, porque no es que el token sea
    inválido.
    """
    try:
        token = _extract_bearer(request.headers.get("Authorization"))
        claims = await validate_access_token(token)
        user_id, email = _identity_from_claims(claims)
    except TokenError as exc:
        logger.warning("Autenticación rechazada: %s", exc.reason)
        raise _unauthorized() from exc
    except JWKSUnavailable as exc:
        logger.error("No se pudo validar el token: JWKS no disponible.")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _SERVICE_UNAVAILABLE_DETAIL
        ) from exc

    try:
        profile = await _resolve_or_create_profile(user_id=user_id, email=email)
    except SQLAlchemyError as exc:
        # Sin traza ni mensaje del error: podría contener la URL de la base (con
        # credenciales). Solo el id del usuario, que no es secreto.
        logger.error("No se pudo resolver el perfil local del usuario %s.", user_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _SERVICE_UNAVAILABLE_DETAIL
        ) from exc

    return CurrentUser(id=profile.id, email=profile.email, plan=profile.plan)
