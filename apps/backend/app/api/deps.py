"""Dependencias de FastAPI compartidas por los endpoints.

``get_current_user`` es el middleware de autenticación: valida el JWT de
Supabase, resuelve el PERFIL LOCAL del usuario y —punto ÚNICO de
materialización— lo crea de forma perezosa e idempotente si aún no existe.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.database import get_db
from app.core.security import JWKSUnavailable, TokenError, validate_access_token
from app.models import Plan, UserProfile

logger = logging.getLogger(__name__)

# Cuerpo y cabecera UNIFORMES para cualquier fallo de autenticación: no se
# revela el motivo (expirado, firma, usuario inexistente…). El motivo real va
# al log del servidor.
_UNAUTHORIZED_DETAIL = "No autenticado."
_SERVICE_UNAVAILABLE_DETAIL = "Servicio no disponible temporalmente."


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
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Valida el JWT de Supabase y resuelve (o crea) el perfil local del usuario.

    Cualquier fallo de autenticación → 401 UNIFORME (mismo cuerpo para todos
    los motivos); el motivo real se registra en el log. Un problema de infra
    (JWKS o base de datos no disponibles) → 503, porque no es que el token sea
    inválido.
    """
    try:
        token = _extract_bearer(authorization)
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
