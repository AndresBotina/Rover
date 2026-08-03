"""Rate limiting PROPIO de la API (HU-1.7): almacén, política y clave.

Aquí vive el núcleo, sin nada de FastAPI: el almacén que cuenta, la política
que decide cuántas peticiones caben, y cómo se obtiene la IP del cliente. La
APLICACIÓN de todo esto (el middleware por IP y la dependencia por usuario)
vive en ``app/api``.

Este rate limiting es el de la API; el ``429`` que ya devolvía ``services/auth``
viene de **Supabase** y es otra cosa. Los dos salen con el mismo ``code``
(``rate_limited``) a propósito: ver la nota al final de este docstring.


## Algoritmo: ventana deslizante por marcas de tiempo

Se guardan las marcas de tiempo de las peticiones de cada clave y se cuenta
cuántas caen dentro de los últimos ``window_seconds``. Frente a las
alternativas:

- **Ventana fija** (un contador por bloque de minuto) es lo más barato, pero
  permite el doble del límite a caballo del corte: con 10/min, diez peticiones
  a las 11:59:59 y diez a las 12:00:00 son veinte en dos segundos. Justo el
  agujero que importa en ``/v1/auth/login``, que es donde se defiende una
  contraseña.
- **Token bucket** es igual de barato en memoria y suaviza el tráfico, pero su
  configuración natural es "capacidad + tasa de recarga", no "N peticiones por
  ventana" —que es como está escrita esta HU y como se hablará de las cuotas
  por plan—, y el ``Retry-After`` sale de un cálculo menos directo.
- **Ventana deslizante por marcas** cuesta O(N) marcas por clave, pero N es el
  propio límite (aquí entre 10 y 120): unos cientos de bytes por clave. A
  cambio es EXACTA (no hay ráfaga de borde) y el ``Retry-After`` es el tiempo
  que falta para que la marca más antigua salga de la ventana — un dato real,
  no una estimación.

Con límites pequeños, la exactitud sale casi gratis: por eso se elige esta.


## Por qué el almacén es una interfaz

Hoy la implementación es **en memoria** (``InMemoryRateLimitStore``), y eso
tiene una limitación que hay que tener MUY presente:

    con varias instancias del backend, el conteo NO es global: cada proceso
    cuenta lo suyo, así que el límite efectivo se multiplica por el número de
    instancias.

Es aceptable HOY porque el despliegue es de una sola instancia (Render, plan
free). El día que haya más de una, se sustituye la implementación —y NADA más:
ni la política, ni el middleware, ni los endpoints—. Cómo sería con Redis:

    async def hit(self, key, *, limit, window_seconds):
        # Un script Lua (o un MULTI) sobre un ZSET por clave, para que las
        # cuatro operaciones sean atómicas igual que aquí lo es el bloque
        # bajo el lock:
        #   ZREMRANGEBYSCORE key -inf (now - window)   # tira lo viejo
        #   ZADD             key now <miembro único>   # registra
        #   ZCARD            key                       # cuenta
        #   EXPIRE           key window                # que se limpie solo

El ZSET es la misma estructura conceptual que el ``deque`` de abajo, así que la
interfaz no cambia. Se pospone porque una segunda instancia no existe todavía y
Redis añadiría, desde ya, un salto de red en CADA petición y una decisión nueva
que hoy no hace falta tomar (si Redis cae, ¿se deja pasar el tráfico o se
corta?).


## Nota sobre el ``code`` unificado

El ``429`` de este módulo y el que nace de un rechazo de Supabase comparten
``ErrorCode.RATE_LIMITED``. Es deliberado: el catálogo de ``code`` es de
DOMINIO, no de origen (ver ``app/core/errors.py``), la acción del cliente es
idéntica en ambos casos —esperar y reintentar— y distinguirlos revelaría que
hay un proveedor detrás, que es justo lo que el diseño de errores evita. Lo
que sí cambia es que el nuestro trae ``Retry-After`` con un valor exacto.
"""

import asyncio
import ipaddress
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from starlette.requests import Request

from app.core.config import settings

# Mensaje del 429: el mismo por las dos vías (middleware y dependencia).
RATE_LIMIT_MESSAGE = "Demasiadas peticiones; espera un momento antes de reintentar."

# Clave de reserva cuando no hay una IP utilizable (cliente sin dirección,
# cabecera ilegible). Todas esas peticiones comparten cubo: es lo conservador
# —antes limitarlas juntas que no limitarlas—, y en la práctica no ocurre
# detrás de un proxy que sí pone la cabecera.
UNKNOWN_CLIENT = "desconocida"

# Cada cuánto se barren las claves inactivas del almacén en memoria. Sin esto,
# un escaneo desde miles de IPs dejaría una entrada por IP para siempre.
_PURGE_INTERVAL_SECONDS = 300.0


class RateLimitScope(StrEnum):
    """Grupos de endpoints con límites distintos.

    Entra en la clave del almacén, así que cada ámbito lleva su propio
    contador: gastar el cupo de ``/v1/auth/login`` no consume el global.
    """

    # Toda la API: protección base de la infraestructura, por IP.
    GLOBAL = "global"
    # Login y registro: fuerza bruta de contraseñas y alta masiva de cuentas.
    AUTH = "auth"
    # Cuota del usuario autenticado, por id del token. Es la que dependerá del
    # plan (ver ``rule_for_user``).
    USER = "user"


@dataclass(frozen=True)
class RateLimitRule:
    """Cuántas peticiones caben en cuánto tiempo, para un ámbito."""

    scope: RateLimitScope
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitResult:
    """Veredicto de una consulta al almacén.

    ``retry_after_seconds`` solo tiene sentido cuando ``allowed`` es falso: es
    el tiempo EXACTO que falta para que la marca más antigua salga de la
    ventana y quede sitio (redondeado hacia arriba, mínimo 1 — un
    ``Retry-After: 0`` invitaría a reintentar de inmediato).
    """

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimitStore(Protocol):
    """Almacén del conteo por clave. La ÚNICA pieza que cambia al ir a Redis.

    ``hit`` registra y consulta **en una sola operación atómica** a propósito:
    partirlo en "consultar" + "registrar" reabre la ventana entre ambos (dos
    peticiones simultáneas leen "queda sitio" y las dos registran, superando el
    límite). ``peek`` existe para consultar SIN consumir, que es otra cosa.
    """

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        """Registra una petición para ``key`` y devuelve si estaba permitida.

        Cuando NO lo está, la petición no se registra: un cliente bloqueado que
        insiste no alarga su propio castigo.
        """
        ...

    async def peek(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        """Consulta el estado de ``key`` sin consumir cupo."""
        ...

    async def reset(self) -> None:
        """Vacía el almacén (arranque limpio; se usa para aislar tests)."""
        ...


class InMemoryRateLimitStore:
    """Ventana deslizante en memoria del proceso. Segura para asyncio.

    LIMITACIÓN CONOCIDA: el conteo es POR PROCESO. Con varias instancias del
    backend cada una cuenta lo suyo y el límite efectivo se multiplica por el
    número de instancias. Ver el docstring del módulo: es aceptable con una
    sola instancia y el punto de cambio es esta clase, nada más.

    El ``asyncio.Lock`` hace que el bloque leer-decidir-escribir sea atómico.
    Hoy el bloque no contiene ningún ``await``, así que asyncio no podría
    intercalar otra tarea aunque no hubiera lock; el lock está porque la
    atomicidad es parte del CONTRATO de la interfaz (``hit``), y en cuanto la
    implementación espere algo —Redis— deja de ser gratis.

    ``now`` es inyectable para poder probar el paso de la ventana sin dormir.
    Por defecto ``time.monotonic``: inmune a que alguien cambie la hora del
    sistema, que con ``time.time`` regalaría o congelaría cupo.
    """

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._now = time.monotonic if now is None else now
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._last_purge = self._now()
        # Ventana más larga vista: el barrido no puede tirar una clave cuyas
        # marcas aún podrían contar para alguna ventana en uso.
        self._max_window = 0.0

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        async with self._lock:
            ahora = self._now()
            self._max_window = max(self._max_window, float(window_seconds))
            marcas = self._hits.setdefault(key, deque())
            _descartar_vencidas(marcas, ahora, window_seconds)

            if len(marcas) >= limit:
                return _rechazo(limit, ahora - marcas[0], window_seconds)

            marcas.append(ahora)
            self._purgar_si_toca(ahora)
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - len(marcas),
                retry_after_seconds=0,
            )

    async def peek(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        async with self._lock:
            ahora = self._now()
            marcas = self._hits.get(key)
            if marcas is None:
                return RateLimitResult(
                    allowed=True, limit=limit, remaining=limit, retry_after_seconds=0
                )
            _descartar_vencidas(marcas, ahora, window_seconds)
            if len(marcas) >= limit:
                return _rechazo(limit, ahora - marcas[0], window_seconds)
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - len(marcas),
                retry_after_seconds=0,
            )

    async def reset(self) -> None:
        async with self._lock:
            self._hits.clear()
            self._last_purge = self._now()
            self._max_window = 0.0

    def _purgar_si_toca(self, ahora: float) -> None:
        """Tira las claves cuya última petición ya no cuenta para NINGUNA ventana.

        Amortizado: se hace como mucho cada ``_PURGE_INTERVAL_SECONDS``, dentro
        del lock que ya se tenía, así que no añade sincronización.
        """
        if ahora - self._last_purge < _PURGE_INTERVAL_SECONDS:
            return
        self._last_purge = ahora
        limite = ahora - self._max_window
        self._hits = {clave: marcas for clave, marcas in self._hits.items() if marcas[-1] > limite}


def _descartar_vencidas(marcas: deque[float], ahora: float, window_seconds: int) -> None:
    """Saca del extremo antiguo las marcas que ya salieron de la ventana."""
    corte = ahora - window_seconds
    while marcas and marcas[0] <= corte:
        marcas.popleft()


def _rechazo(limit: int, antiguedad: float, window_seconds: int) -> RateLimitResult:
    """Veredicto negativo, con el tiempo que falta para que se libere un hueco."""
    espera = window_seconds - antiguedad
    return RateLimitResult(
        allowed=False,
        limit=limit,
        remaining=0,
        retry_after_seconds=max(1, math.ceil(espera)),
    )


# --- Almacén por defecto del proceso -----------------------------------------
# Mismo patrón que la caché del JWKS en app/core/security.py: un singleton de
# módulo con su función de reinicio, para que las piezas que lo usan (el
# middleware, la dependencia) no tengan que pasárselo unas a otras.

_store: RateLimitStore = InMemoryRateLimitStore()


def get_rate_limit_store() -> RateLimitStore:
    """Almacén que usan el middleware y la dependencia.

    Se consulta en CADA petición (no se captura al construir el middleware)
    para que reemplazarlo —al migrar a Redis, o en un test— tenga efecto sin
    reconstruir la app.
    """
    return _store


def reset_rate_limit_store(store: RateLimitStore | None = None) -> None:
    """Instala un almacén vacío. Sin argumento, uno en memoria nuevo.

    Es también el gancho de la migración a Redis: ``create_app`` (o un módulo
    de arranque) llamaría a esto con la implementación Redis y ni el
    middleware, ni la dependencia, ni ningún endpoint se enterarían.
    """
    global _store
    _store = InMemoryRateLimitStore() if store is None else store


# --- Política: qué límite le toca a cada petición ----------------------------


def rule_for_scope(scope: RateLimitScope) -> RateLimitRule:
    """Regla configurada para un ámbito NO ligado al usuario (global o auth).

    Se leen los settings en cada llamada (son atributos en memoria, no cuesta
    nada) para que ajustar un límite no obligue a reconstruir la app.
    """
    if scope is RateLimitScope.AUTH:
        return RateLimitRule(
            scope=scope,
            limit=settings.rate_limit_auth_limit,
            window_seconds=settings.rate_limit_auth_window_seconds,
        )
    if scope is RateLimitScope.USER:  # pragma: no cover - USER pasa por rule_for_user
        return rule_for_user()
    return RateLimitRule(
        scope=RateLimitScope.GLOBAL,
        limit=settings.rate_limit_default_limit,
        window_seconds=settings.rate_limit_default_window_seconds,
    )


def rule_for_user(*, multiplier: float = 1.0) -> RateLimitRule:
    """Cuota del usuario autenticado, escalada por ``multiplier``.

    **ESTE es el punto de extensión de los límites por plan.** El llamador
    (``app/api/deps.py``, único sitio donde se conoce el plan) traduce el plan
    a un multiplicador; hoy free y pro valen lo mismo porque
    ``ROVER_RATE_LIMIT_PRO_MULTIPLIER`` es ``1.0``. Subirlo a 5 da a los planes
    de pago cinco veces el cupo sin tocar una línea de código.

    Se modela como multiplicador y no como un límite por plan porque lo que
    cambia entre planes es la MAGNITUD, no la forma; así añadir un tercer plan
    (Épica 5) es una entrada más en el mapa de ``deps.py``, y las cuotas de
    consumo del agente (Épica 2) pueden colgar de aquí como ámbitos nuevos con
    su propia regla en vez de reabrir esta.
    """
    return RateLimitRule(
        scope=RateLimitScope.USER,
        limit=max(1, int(settings.rate_limit_user_limit * multiplier)),
        window_seconds=settings.rate_limit_user_window_seconds,
    )


def make_key(scope: RateLimitScope, kind: str, value: str) -> str:
    """Clave del almacén: ``ámbito:tipo:valor``.

    El ámbito va dentro para que cada grupo de endpoints cuente por separado, y
    el tipo para que una IP y un id de usuario nunca colisionen.
    """
    return f"{scope}:{kind}:{value}"


def rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    """Cabeceras que acompañan al 429.

    ``Retry-After`` en segundos (RFC 9110): es la única que un cliente necesita
    para reintentar bien, y la que ``@rover/shared`` lee. Las ``X-RateLimit-*``
    son convención, no estándar, y se mandan SOLO aquí —no en las respuestas
    correctas— por dos razones: envolver cada respuesta para añadirlas costaría
    interceptar el ``send`` de todas, y publicar el cupo restante a cualquiera
    que pregunte le dice a quien sondea exactamente cuánto margen le queda.
    """
    return {
        "Retry-After": str(result.retry_after_seconds),
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.retry_after_seconds),
    }


# --- IP del cliente detrás del proxy -----------------------------------------


def client_ip(request: Request, *, trusted_proxies: int) -> str:
    """IP real del cliente, contando desde el proxy hacia fuera.

    ``X-Forwarded-For`` es una lista donde **cada proxy AÑADE al final** la
    dirección de quien le habló. La primera entrada es la que puso el cliente
    y es FALSIFICABLE: cualquiera puede mandar ``X-Forwarded-For: 1.2.3.4`` y,
    si se leyera la primera, se saltaría el rate limiting cambiando de valor en
    cada petición (y de paso llenaría el almacén de claves inventadas).

    Lo único fiable es lo que añadieron los proxies de CONFIANZA, que está a la
    DERECHA. Con ``trusted_proxies`` saltos de confianza, la IP del cliente es
    la entrada ``trusted_proxies``-ésima empezando por el final::

        cliente miente ─┐        ┌─ lo añade el proxy de Render (fiable)
                        ▼        ▼
        X-Forwarded-For: 1.2.3.4, 203.0.113.7
                                  ─────┬─────
                     trusted_proxies=1 ┘  → 203.0.113.7

    En Render hay exactamente un salto (su edge), que es el valor por defecto
    de ``ROVER_RATE_LIMIT_TRUSTED_PROXIES``. Con un proxy más delante (p. ej.
    un CDN) se sube a 2. Con **0** la cabecera se IGNORA por completo y se usa
    el peer TCP: sin ningún proxy de confianza delante, cualquier
    ``X-Forwarded-For`` lo escribió el cliente y no vale nada.

    Si la lista tiene menos entradas válidas de las esperadas —cabecera
    ausente, recortada o con basura—, se cae al peer TCP: es menos preciso
    (puede ser el proxy) pero nunca es falsificable.
    """
    peer = request.client.host if request.client is not None else None

    if trusted_proxies <= 0:
        return _normalizar_ip(peer) or UNKNOWN_CLIENT

    reenviadas: list[str] = []
    for cabecera in request.headers.getlist("x-forwarded-for"):
        reenviadas.extend(cabecera.split(","))
    validas = [ip for ip in (_normalizar_ip(bruta) for bruta in reenviadas) if ip is not None]

    if len(validas) >= trusted_proxies:
        return validas[-trusted_proxies]
    return _normalizar_ip(peer) or UNKNOWN_CLIENT


def _normalizar_ip(valor: str | None) -> str | None:
    """Valida y normaliza una dirección; ``None`` si no es una IP.

    Validar no es cosmético: sin esto, una cabecera con basura distinta en cada
    petición crearía una clave nueva cada vez —el almacén crecería sin
    límite— además de esquivar el conteo.

    Acepta que algún proxy añada el puerto (``1.2.3.4:5678``,
    ``[2001:db8::1]:5678``) y normaliza la forma de las IPv6, para que dos
    escrituras de la misma dirección no acaben en dos cubos distintos.
    """
    if valor is None:
        return None
    candidato = valor.strip()
    if not candidato:
        return None

    if candidato.startswith("["):  # IPv6 entre corchetes, con o sin puerto
        cierre = candidato.find("]")
        if cierre == -1:
            return None
        candidato = candidato[1:cierre]
    elif candidato.count(":") == 1:  # IPv4 con puerto (una IPv6 tiene más ':')
        candidato = candidato.split(":", 1)[0]

    try:
        return str(ipaddress.ip_address(candidato))
    except ValueError:
        return None
