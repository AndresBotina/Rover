"""Dependencias de FastAPI compartidas por los endpoints.

``get_current_user`` es el middleware de autenticación: valida el JWT de
Supabase, resuelve el PERFIL LOCAL del usuario y —punto ÚNICO de
materialización— lo crea de forma perezosa e idempotente si aún no existe.
"""

import logging
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request, status
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import ApiError, ErrorCode, error_doc
from app.core.rate_limit import (
    RATE_LIMIT_MESSAGE,
    get_rate_limit_store,
    make_key,
    rate_limit_headers,
    rule_for_user,
)
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
    401: error_doc(
        "`unauthenticated` — falta el token, o no es válido (formato, firma, "
        "expiración, issuer o audiencia). El cuerpo es **uniforme** para todos "
        "los motivos; el motivo real solo va al log del servidor."
    ),
    429: error_doc(
        "`rate_limited` — se agotó la cuota de peticiones de la cuenta "
        "(HU-1.7). La cabecera `Retry-After` dice en cuántos segundos "
        "reintentar."
    ),
    503: error_doc(
        "`service_unavailable` — fallo de infraestructura propia (el JWKS de "
        "Supabase o la base de datos no están disponibles). No implica que el "
        "token sea inválido."
    ),
}


@dataclass(frozen=True)
class CurrentUser:
    """Identidad resuelta del request: disponible para los endpoints protegidos."""

    id: uuid.UUID
    email: str
    plan: Plan


def _unauthorized() -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        ErrorCode.UNAUTHENTICATED,
        _UNAUTHORIZED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _service_unavailable() -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorCode.SERVICE_UNAVAILABLE,
        _SERVICE_UNAVAILABLE_DETAIL,
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

    ``aclosing`` no es decorativo: esta función SALE con ``return`` desde dentro
    del ``async for``, y eso deja el generador de ``get_db`` suspendido en su
    ``yield`` — con la sesión (y su conexión) abiertas hasta que pase el
    recolector. ``aclosing`` lo cierra en el momento, que es lo que hace
    ``Depends`` cuando la dependencia se inyecta de la forma normal.
    """
    async with aclosing(get_db()) as sesiones:
        async for session in sesiones:
            existing = await session.get(UserProfile, user_id)
            if existing is not None:
                return existing

            profile = UserProfile(id=user_id, email=email)
            session.add(profile)
            try:
                await session.commit()
            except IntegrityError:
                # Otra petición creó el perfil entre el get y el commit: no es
                # un error, es la carrera esperada. Se relee la fila existente.
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
        raise _service_unavailable() from exc

    try:
        profile = await _resolve_or_create_profile(user_id=user_id, email=email)
    except SQLAlchemyError as exc:
        # Sin traza ni mensaje del error: podría contener la URL de la base (con
        # credenciales). Solo el id del usuario, que no es secreto.
        logger.error("No se pudo resolver el perfil local del usuario %s.", user_id)
        raise _service_unavailable() from exc

    return CurrentUser(id=profile.id, email=profile.email, plan=profile.plan)


# --- Cuota por usuario (HU-1.7) ----------------------------------------------
# El middleware (app/api/middleware.py) limita por IP; esto limita por CUENTA.
# Va aquí y no allí porque la identidad no existe hasta que get_current_user
# valida el token: FastAPI cachea esa dependencia, así que resolver el usuario
# no se paga dos veces.


# PUNTO DE EXTENSIÓN de los límites por plan (Épica 5, monetización). Hoy free
# y pro pesan igual porque ROVER_RATE_LIMIT_PRO_MULTIPLIER vale 1.0; subirlo da
# más cupo a los planes de pago sin tocar código. Un plan nuevo es una entrada
# más en este mapa, y las cuotas de consumo del agente (Épica 2 — tokens de
# LLM, minutos de voz) son ámbitos NUEVOS con su propia regla, no un cambio
# aquí: esto acota peticiones, aquello acotará consumo.
def _multiplicador_del_plan(plan: Plan) -> float:
    return settings.rate_limit_pro_multiplier if plan is Plan.PRO else 1.0


async def enforce_user_rate_limit(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Consume una unidad de la cuota del usuario; 429 cuando se agota.

    Se aplica a TODO el router de ``users`` (y a cualquier router protegido que
    se añada) declarándola en ``include_router``/``APIRouter``, no endpoint a
    endpoint: así una ruta protegida nueva nace con cuota en vez de olvidarla.
    """
    if not settings.rate_limit_enabled:
        return

    regla = rule_for_user(multiplier=_multiplicador_del_plan(user.plan))
    resultado = await get_rate_limit_store().hit(
        make_key(regla.scope, "user", str(user.id)),
        limit=regla.limit,
        window_seconds=regla.window_seconds,
    )
    if resultado.allowed:
        return

    # El id del usuario sí (es la clave para diagnosticar), el email no: no
    # hace falta un dato personal en el log para saber qué cuenta se pasó.
    logger.warning(
        "Rate limit de usuario superado: user_id=%s plan=%s limite=%s/%ss retry_after=%ss",
        user.id,
        user.plan.value,
        regla.limit,
        regla.window_seconds,
        resultado.retry_after_seconds,
    )
    raise ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ErrorCode.RATE_LIMITED,
        RATE_LIMIT_MESSAGE,
        headers=rate_limit_headers(resultado),
    )
