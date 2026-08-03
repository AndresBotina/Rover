"""Middleware de la API. Hoy, el rate limiting por IP (HU-1.7).

Se aplica ANTES de resolver la ruta, a propósito: así también cuenta lo que no
existe. Un escáner que dispara a mil rutas inventadas es exactamente el tráfico
del que hay que defenderse, y con el límite montado como dependencia del router
esas peticiones se irían en 404 sin consumir cupo.

Es un middleware **ASGI puro** (no ``BaseHTTPMiddleware``): solo mira la ruta y
las cabeceras para decidir, sin tocar el cuerpo, así que no necesita el
envoltorio de streams que aquel monta para cada petición.

Reparto de responsabilidades con la dependencia por usuario de ``app/api/deps``:

- **Aquí, por IP**: protección de la infraestructura. Es lo único disponible
  cuando aún no se sabe quién llama —que es el caso de ``/v1/auth/login`` y
  ``/v1/auth/register``, donde precisamente hace falta.
- **Allí, por usuario**: la cuota de la cuenta, ligada al plan. No puede vivir
  aquí porque la identidad no existe hasta que ``get_current_user`` valida el
  token; repetir esa validación en un middleware pagaría dos veces el JWKS y la
  consulta del perfil.

Que una ruta protegida pase por los dos no es un descuido: son controles
distintos (la máquina y la cuenta) y el más estricto es el que manda.
"""

import logging

from fastapi import status
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.errors import ErrorCode, error_response
from app.core.rate_limit import (
    RATE_LIMIT_MESSAGE,
    RateLimitScope,
    client_ip,
    get_rate_limit_store,
    make_key,
    rate_limit_headers,
    rule_for_scope,
)

logger = logging.getLogger(__name__)

# Endpoints de auth: límite estricto (fuerza bruta, alta masiva de cuentas).
_RUTAS_AUTH = frozenset({"/v1/auth/login", "/v1/auth/register"})

# Sondas de salud, EXENTAS. Render consulta /v1/health constantemente desde sus
# propias direcciones para decidir si el deploy está sano; gastarles cupo
# arriesga marcar como caída una instancia que funciona, y son respuestas sin
# coste que no interesa a nadie abusar.
_RUTAS_EXENTAS = frozenset({"/v1/health", "/v1/health/db"})


class RateLimitMiddleware:
    """Cuenta las peticiones por IP y corta con un 429 cuando se pasan."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        ruta = _normalizar_ruta(request.url.path)
        if ruta in _RUTAS_EXENTAS:
            await self.app(scope, receive, send)
            return

        ambito = RateLimitScope.AUTH if ruta in _RUTAS_AUTH else RateLimitScope.GLOBAL
        regla = rule_for_scope(ambito)
        ip = client_ip(request, trusted_proxies=settings.rate_limit_trusted_proxies)

        resultado = await get_rate_limit_store().hit(
            make_key(ambito, "ip", ip),
            limit=regla.limit,
            window_seconds=regla.window_seconds,
        )
        if resultado.allowed:
            await self.app(scope, receive, send)
            return

        # Nivel warning: no es un fallo del servicio, pero sí algo que mirar si
        # se repite. Se registran la IP y la ruta (lo accionable para
        # diagnosticar abuso, y lo que cualquier log de acceso ya tiene) y
        # NUNCA el token, las cabeceras ni la query string.
        logger.warning(
            "Rate limit superado: ambito=%s ip=%s ruta=%s limite=%s/%ss retry_after=%ss",
            ambito.value,
            ip,
            ruta,
            regla.limit,
            regla.window_seconds,
            resultado.retry_after_seconds,
        )
        respuesta = error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ErrorCode.RATE_LIMITED,
            RATE_LIMIT_MESSAGE,
            headers=rate_limit_headers(resultado),
        )
        await respuesta(scope, receive, send)


def _normalizar_ruta(path: str) -> str:
    """Quita la barra final para que ``/v1/auth/login/`` no esquive el ámbito."""
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path
