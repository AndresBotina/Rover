"""Validación LOCAL de los JWT emitidos por Supabase Auth.

El backend NO pregunta a Supabase por cada petición (eso añadiría latencia y
una dependencia dura del proveedor en el camino crítico de toda la API):
verifica la firma él mismo. Supabase firma con claves asimétricas ES256
publicadas en un JWKS; cada token trae un ``kid`` en la cabecera que
selecciona la clave.

Se valida MÁS que la firma: expiración (``exp``), issuer (``iss``) y audiencia
(``aud``) del proyecto. Un token con firma válida pero de otro proyecto, sin
``sub``, o expirado, se rechaza.

Caché del JWKS (política): se guarda el set en memoria con un **TTL** (por
defecto 10 min); mientras esté fresco no se vuelve a pedir. Si llega un token
con un ``kid`` que no está en el set (posible **rotación de claves**), se fuerza
UN refresco — pero con un **cooldown** mínimo entre refrescos, para que una
lluvia de tokens con kid inválido no golpee el endpoint del JWKS en cada
petición. Un ``asyncio.Lock`` evita refrescos concurrentes.

Los fallos se traducen a ``TokenError`` con un ``reason`` PRECISO (para el log);
la capa de API los convierte en un 401 uniforme. Un problema de INFRAESTRUCTURA
(no se puede traer el JWKS) es distinto: ``JWKSUnavailable`` → la API responde
503, porque no es que el token del cliente sea inválido.
"""

import time
from typing import Any

import httpx
import jwt

from app.core.config import settings

# Audiencia estándar de los usuarios autenticados de Supabase.
_EXPECTED_AUDIENCE = "authenticated"
_ALGORITHMS = ["ES256"]
_TIMEOUT_SECONDS = 10.0

# Política de caché del JWKS.
_JWKS_TTL_SECONDS = 600.0  # 10 min: mientras esté fresco, no se re-pide.
_JWKS_MIN_REFRESH_INTERVAL = 30.0  # cooldown entre refrescos forzados por kid.


class TokenError(Exception):
    """Token inválido. ``reason`` es PRECISO para el log; el cliente ve un 401 uniforme."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JWKSUnavailable(Exception):
    """No se pudo obtener el JWKS (infra del proveedor): no es culpa del token → 503."""


def _base_url() -> str:
    """URL del proyecto de Supabase, sin barra final, o falla si no está configurada."""
    if settings.supabase_url is None:
        raise JWKSUnavailable("ROVER_SUPABASE_URL no está configurada.")
    return settings.supabase_url.rstrip("/")


def _jwks_url() -> str:
    return f"{_base_url()}/auth/v1/.well-known/jwks.json"


def _expected_issuer() -> str:
    return f"{_base_url()}/auth/v1"


async def _fetch_jwks() -> jwt.PyJWKSet:
    """Descarga y parsea el JWKS del proyecto (async, sin caché — la caché la
    gestiona ``_JWKSCache``)."""
    url = _jwks_url()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        response.raise_for_status()
        return jwt.PyJWKSet.from_dict(response.json())
    except (httpx.HTTPError, ValueError, jwt.PyJWTError) as exc:
        raise JWKSUnavailable("No se pudo obtener el JWKS de Supabase.") from exc


class _JWKSCache:
    """Caché en memoria del JWKS, con TTL y refresco por ``kid`` desconocido."""

    def __init__(self) -> None:
        self._jwks: jwt.PyJWKSet | None = None
        self._fetched_at = 0.0
        # Solo los refrescos FORZADOS (por kid desconocido) cuentan para el
        # cooldown; None = aún no se ha forzado ninguno.
        self._last_forced_refresh: float | None = None

    def reset(self) -> None:
        """Vacía la caché (para aislar tests)."""
        self._jwks = None
        self._fetched_at = 0.0
        self._last_forced_refresh = None

    async def get_signing_key(self, kid: str) -> jwt.PyJWK:
        """Devuelve la clave de firma con ese ``kid``, refrescando si hace falta.

        Refresca cuando el ``kid`` no está en el set cacheado (rotación), pero
        respetando el cooldown para no martillar el endpoint del JWKS.
        """
        jwks = await self._get(force=False)
        key = _find_key(jwks, kid)
        if key is None:
            jwks = await self._get(force=True)
            key = _find_key(jwks, kid)
        if key is None:
            raise TokenError("unknown_kid")
        return key

    async def _get(self, *, force: bool) -> jwt.PyJWKSet:
        now = time.monotonic()

        # Carga inicial: aún no hay nada cacheado. No cuenta como refresco
        # forzado, así que el primer refresco por kid desconocido sí procederá.
        if self._jwks is None:
            self._jwks = await _fetch_jwks()
            self._fetched_at = now
            return self._jwks

        if not force:
            if (now - self._fetched_at) < _JWKS_TTL_SECONDS:
                return self._jwks
            # TTL vencido: recarga normal.
            self._jwks = await _fetch_jwks()
            self._fetched_at = now
            return self._jwks

        # force=True (kid desconocido → posible rotación), con cooldown: si se
        # forzó un refresco hace muy poco, se devuelve lo cacheado (el llamador
        # rechazará el token) en vez de golpear el JWKS en cada petición.
        if (
            self._last_forced_refresh is not None
            and (now - self._last_forced_refresh) < _JWKS_MIN_REFRESH_INTERVAL
        ):
            return self._jwks
        self._last_forced_refresh = now
        self._jwks = await _fetch_jwks()
        self._fetched_at = now
        return self._jwks


def _find_key(jwks: jwt.PyJWKSet, kid: str) -> jwt.PyJWK | None:
    for key in jwks.keys:
        if key.key_id == kid:
            return key
    return None


_jwks_cache = _JWKSCache()


def reset_jwks_cache() -> None:
    """Vacía la caché del JWKS (para aislar tests)."""
    _jwks_cache.reset()


async def validate_access_token(token: str) -> dict[str, Any]:
    """Valida un access token de Supabase y devuelve sus claims, o lanza TokenError.

    Verifica firma (ES256, clave por ``kid`` del JWKS), expiración, issuer y
    audiencia, y exige ``sub``. Cada modo de fallo produce un ``reason``
    distinto para el log.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TokenError("malformed") from exc

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise TokenError("missing_kid")

    signing_key = await _jwks_cache.get_signing_key(kid)

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=_ALGORITHMS,
            audience=_EXPECTED_AUDIENCE,
            issuer=_expected_issuer(),
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenError("invalid_audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenError("invalid_issuer") from exc
    except jwt.MissingRequiredClaimError as exc:
        raise TokenError("missing_claim") from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenError("invalid_signature") from exc
    except jwt.PyJWTError as exc:
        # Cualquier otro fallo de validación (formato, algoritmo, etc.).
        raise TokenError("invalid_token") from exc

    return claims
