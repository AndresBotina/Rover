"""Middleware de la API: contexto de petición (HU-1.12), CORS (HU-1.11) y
rate limiting por IP (HU-1.7).

ORDEN DE LA PILA (importa, y no es arbitrario). Starlette monta el último
``add_middleware`` como el más externo, así que ``create_app`` los añade al
revés del orden en que corren. De fuera hacia dentro:

    RequestContext → CORS → RateLimit → rutas

- **RequestContext, el más externo**, para que TODO lo que pase dentro —incluido
  un rechazo del rate limiter o un preflight que CORS corta en seco— tenga id
  de petición en sus logs y en su respuesta. Es también quien mide la duración
  real, con los otros middlewares dentro.
- **CORS por fuera del rate limiting**, porque las cabeceras de CORS se añaden a
  la RESPUESTA al salir: si CORS quedara por dentro, el 429 que corta el rate
  limiter saldría sin ellas y el navegador se lo ocultaría al JavaScript como
  un error de CORS genérico — la web no podría distinguir "te pasaste de
  peticiones" de "el servidor no responde", ni leer ``Retry-After``.

Contrapartida asumida: el preflight (OPTIONS) lo responde CORS sin llegar al
rate limiter, así que no consume cupo. Es barato (no toca ruta, ni base, ni
JWKS) y no abre nada: quien quiera abusar manda peticiones reales, que sí
cuentan.

--- Rate limiting ---

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
import time

from fastapi import FastAPI, status
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
from app.core.request_context import (
    REQUEST_ID_HEADER,
    new_request_id,
    reset_request_id,
    sanitize_request_id,
    set_request_id,
    store_request_id,
)

logger = logging.getLogger(__name__)

# El log de acceso va en su PROPIO logger, no en el del módulo: es un flujo
# distinto —una línea por petición, siempre— frente a los eventos puntuales del
# resto de la app, y quien opera querrá filtrarlo o bajarle el nivel por
# separado sin perder los diagnósticos. Es el sustituto de ``uvicorn.access``,
# que este proyecto silencia (ver app/core/logging.py).
access_logger = logging.getLogger("app.access")

# Endpoints de auth: límite estricto (fuerza bruta, alta masiva de cuentas).
_RUTAS_AUTH = frozenset({"/v1/auth/login", "/v1/auth/register"})

# Sondas de salud, EXENTAS. Render consulta /v1/health constantemente desde sus
# propias direcciones para decidir si el deploy está sano; gastarles cupo
# arriesga marcar como caída una instancia que funciona, y son respuestas sin
# coste que no interesa a nadie abusar.
_RUTAS_EXENTAS = frozenset({"/v1/health", "/v1/health/db"})

# --- Contexto de petición y log de acceso (HU-1.12) --------------------------


def _nivel_por_status(status_code: int) -> int:
    """5xx es un fallo nuestro; 4xx, algo que el cliente debe corregir."""
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return logging.ERROR
    if status_code >= status.HTTP_400_BAD_REQUEST:
        return logging.WARNING
    return logging.INFO


class RequestContextMiddleware:
    """Da a cada petición un id, lo propaga, lo devuelve y la registra.

    El id sale de la cabecera ``X-Request-ID`` si viene una válida —así una
    traza que empieza en un proxy o en la web sigue siendo la misma aquí— y si
    no, se genera. Lo entrante se sanea antes de usarse
    (``app/core/request_context.py``): acaba en los logs y en una cabecera, así
    que un salto de línea permitiría falsificar registros.

    QUÉ SE REGISTRA de cada petición: método, RUTA, status y duración. Lo que
    NO: el cuerpo, las cabeceras (``Authorization`` lleva el token) y la QUERY
    STRING. Esta última es una política deliberada y no una omisión — hoy
    ningún endpoint recibe nada sensible por query, pero los que suelen llegar
    después (búsquedas, enlaces de confirmación con código, filtros con datos
    del usuario) sí, y para entonces nadie se acordaría de revisar este
    middleware. La ruta basta para saber qué se llamó.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        entrante = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request_id = entrante or new_request_id()
        token = set_request_id(request_id)
        # Además del contexto, en el scope: el handler de los 500 corre por
        # fuera de este middleware y para entonces el contexto ya se restauró.
        store_request_id(scope, request_id)

        # Si la petición revienta, la respuesta la construye el handler de
        # errores por FUERA de este middleware: el status que se registra es el
        # 500 que va a salir.
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        inicio = time.perf_counter()

        async def send_con_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # Asignar y no añadir: si algo más lo hubiera puesto ya, no
                # queremos dos cabeceras con ids distintos.
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_con_id)
        finally:
            duracion_ms = round((time.perf_counter() - inicio) * 1000, 2)
            access_logger.log(
                _nivel_por_status(status_code),
                "%s %s → %s (%s ms)",
                request.method,
                request.url.path,
                status_code,
                duracion_ms,
                extra={
                    "http_method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": duracion_ms,
                },
            )
            reset_request_id(token)


# --- CORS (HU-1.11) ----------------------------------------------------------
# Qué es CORS y qué NO protege: es una regla que aplica el NAVEGADOR para que
# una página cualquiera no pueda leer respuestas de esta API con la sesión de
# quien la visita. No es un control de acceso del servidor —curl, Postman o el
# móvil (Expo) ignoran todo esto—; la autorización de verdad sigue siendo el
# Bearer (HU-1.6) y los límites (HU-1.7).

# Métodos que la API usa hoy. Explícitos y no "*": la lista es la superficie
# que un navegador puede intentar, y ampliarla debería ser una decisión.
# OPTIONS va incluido porque es el que trae el preflight.
CORS_METODOS = ("GET", "POST", "PATCH", "OPTIONS")

# Cabeceras que los clientes ENVÍAN. ``Content-Type: application/json`` no es
# un valor "simple" según la spec, así que sin declararlo el preflight
# rechazaría cualquier POST con cuerpo JSON (registro, login);
# ``Authorization`` es el Bearer de Supabase de las rutas protegidas; y
# ``X-Request-ID`` deja que la web propague su propia traza (HU-1.12).
CORS_CABECERAS = ("Authorization", "Content-Type", REQUEST_ID_HEADER)

# Cabeceras de RESPUESTA que el JavaScript del navegador puede LEER. Por
# defecto solo ve un puñado de cabeceras "safelisted", y NINGUNA de estas lo
# es: sin exponerlas, ``parseRetryAfter`` y ``ApiError.retryAfterSeconds`` de
# @rover/shared (HU-1.7) leerían siempre null en web aunque el 429 las traiga,
# y el id de petición (HU-1.12) no se podría mostrar al reportar un fallo.
CORS_CABECERAS_EXPUESTAS = (
    "Retry-After",
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    REQUEST_ID_HEADER,
)

# Cuánto puede cachear el navegador un preflight: ahorra un OPTIONS por cada
# petición sin dejar la política congelada durante horas si hay que cambiarla.
CORS_MAX_AGE_SEGUNDOS = 600

# Credenciales = cookies, certificados de cliente TLS o fetch con
# ``credentials: 'include'``. NO se permiten: la sesión de Rover viaja en la
# cabecera Authorization, no en cookies (ver docs/auth.md), así que activarlas
# no daría nada y ampliaría lo que un origen permitido puede hacer en nombre
# del usuario. Efecto lateral valioso: la combinación INSEGURA "*" + credenciales
# —que el navegador rechaza y que Supabase-style APIs suelen intentar a mano—
# es imposible por construcción. Si algún día la web necesitara cookies contra
# esta API, activarlas obliga a que los orígenes sean siempre explícitos, que
# es lo que ya garantiza el validador de producción en ``Settings``.
CORS_CREDENCIALES = False


def configure_cors(app: FastAPI) -> None:
    """Monta el CORS de FastAPI con los orígenes que toquen al ambiente.

    Los orígenes NUNCA están hardcodeados aquí: salen de
    ``Settings.cors_allowed_origins`` (``ROVER_CORS_ORIGINS``, con defaults de
    desarrollo fuera de producción y ninguno en producción).
    """
    origenes = settings.cors_allowed_origins

    if not origenes:
        # No es un error —la API funciona sin navegadores— pero en producción
        # casi siempre significa que se olvidó la variable, y el síntoma (la
        # web falla con un error de CORS opaco) no apunta al backend. Que
        # quede dicho en el arranque.
        logger.warning(
            "CORS sin orígenes permitidos (env=%s): ninguna web podrá llamar a la API desde "
            "el navegador. Configura ROVER_CORS_ORIGINS con los orígenes de la web.",
            settings.env,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origenes,
        allow_credentials=CORS_CREDENCIALES,
        allow_methods=list(CORS_METODOS),
        allow_headers=list(CORS_CABECERAS),
        expose_headers=list(CORS_CABECERAS_EXPUESTAS),
        max_age=CORS_MAX_AGE_SEGUNDOS,
    )


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
