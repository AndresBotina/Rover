"""Implementación del proveedor de clima sobre OpenWeatherMap.

Todo lo que sabe de OpenWeatherMap vive AQUÍ: sus dos endpoints, su forma de
JSON, sus unidades y sus errores. Hacia fuera solo salen los tipos y las
excepciones de ``base.py``. Quien lo use no puede notar la diferencia con
cualquier otro servicio de clima — que es exactamente la prueba de que el
cambio de proveedor es enchufar otra clase.


## Por qué OpenWeatherMap hoy, y cómo se cambia a Open-Meteo

Se eligió OpenWeatherMap por dos razones prácticas, no por ser mejor:
**geocoding y clima en el mismo servicio y con la misma key** (un solo
proveedor que dar de alta, un solo sitio donde mirar cuota), y **plan gratuito
suficiente** para lo que hace Rover hoy.

**Open-Meteo es la alternativa sin key** y está a una clase de distancia. Su
API tiene la misma forma de dos pasos —``geocoding-api.open-meteo.com/v1/search``
para el nombre y ``api.open-meteo.com/v1/forecast?latitude=&longitude=&current=…``
para el dato—, así que la implementación es este mismo archivo con otras URLs y
otro parseo. El cambio COMPLETO son tres pasos:

1. Escribir ``app/services/weather/openmeteo.py`` con una clase que cumpla el
   ``Protocol`` de ``base.py`` (unas 80 líneas: dos GET y un parseo).
2. Cambiar ``_construir_proveedor()`` en ``registry.py`` para que devuelva esa.
3. Borrar ``ROVER_WEATHER_API_KEY`` del entorno (Open-Meteo no la pide).

Lo que **no** se toca: el loop de tool-calling, el endpoint ``/v1/chat``, la
definición de la herramienta que ve el modelo, ni un solo test de los que
prueban el ciclo — porque ninguno de ellos conoce este archivo. La codificación
de esa promesa es que el único módulo que importa ``openweathermap`` es
``registry.py``.

Nota de la Épica 5: el **uso comercial** de cualquiera de los dos (los términos
del plan gratuito de OpenWeatherMap y la licencia de atribución de Open-Meteo)
se revisa allí, junto con el resto de las APIs de pago. Hoy es una decisión
técnica y reversible, no un compromiso.


## Un cliente HTTP por llamada

Igual que ``services/auth.py`` y ``services/llm/deepseek.py``, y por la misma
razón: un cliente a nivel de módulo queda atado al event loop en el que nació,
y ese acoplamiento ya costó caro en los tests de la Épica 1. El handshake TLS
extra es despreciable frente a la latencia de la propia consulta.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.weather.base import (
    CurrentWeather,
    Place,
    WeatherError,
    WeatherNotFound,
    WeatherUnavailable,
    clean_location,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "openweathermap"

#: Rutas, relativas a la URL base. Se concatenan (no se sustituyen), así que
#: una base con path propio —un proxy interno, un mock— sigue funcionando.
_GEOCODING_PATH = "/geo/1.0/direct"
_WEATHER_PATH = "/data/2.5/weather"

#: Unidades pedidas al proveedor. NO es configuración: el tipo de dominio
#: ``CurrentWeather`` promete grados Celsius, así que dejar que el entorno
#: cambie esto convertiría el contrato en una mentira silenciosa.
_UNITS = "metric"

#: m/s (lo que devuelve el proveedor en unidades métricas) → km/h.
_MS_A_KMH = 3.6

_MSG_CAIDO = "El servicio de clima no está respondiendo."
_MSG_SIN_LUGAR = "No encontré ningún lugar con ese nombre."


class OpenWeatherMapProvider:
    """Proveedor de clima sobre la API de OpenWeatherMap.

    Cumple el ``Protocol`` de ``base.py`` por estructura: no hereda de nada y
    el módulo de la interfaz no lo conoce.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openweathermap.org",
        language: str = "es",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        # Sin barra final: las rutas ya empiezan por "/".
        self._base_url = base_url.rstrip("/")
        self._language = language
        self._timeout = timeout_seconds
        # Punto de inyección para los tests (``httpx.MockTransport``): permite
        # ejercer el camino REAL —cuerpo, query, parseo, traducción de
        # errores— sin red y sin key, igual que en ``deepseek.py``.
        self._transport = transport

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    async def current(self, location: str, *, country_code: str | None = None) -> CurrentWeather:
        """Geocodifica el nombre y pide el clima de esas coordenadas.

        Los dos pasos van encadenados a propósito y no expuestos: ver el
        docstring de ``base.WeatherProvider``.
        """
        lugar = await self._geocode(location, country_code=country_code)
        return await self._clima(lugar)

    # --- Los dos pasos -------------------------------------------------------

    async def _geocode(self, location: str, *, country_code: str | None) -> Place:
        """Nombre de lugar → punto del mapa. Se queda con el PRIMER resultado.

        ``limit=1`` y no un desambiguador: el proveedor ya devuelve los
        resultados por relevancia, y elegir entre varios "Cali" exigiría una
        conversación con el usuario que la herramienta no puede tener. Lo que
        sí se hace es devolver el país en el ``Place``, para que el modelo
        pueda decir de qué Cali está hablando y el usuario corrija si hace
        falta.
        """
        nombre = clean_location(location)
        if not nombre:
            raise WeatherNotFound(_MSG_SIN_LUGAR)

        consulta = f"{nombre},{country_code.strip()}" if country_code else nombre
        cuerpo = await self._get(
            _GEOCODING_PATH, {"q": consulta, "limit": "1"}, contexto="geocoding"
        )
        if not isinstance(cuerpo, list) or not cuerpo or not isinstance(cuerpo[0], dict):
            # Una lista vacía es un 200 perfectamente válido: significa "ese
            # nombre no le suena a nadie", que es un NotFound, no un fallo.
            raise WeatherNotFound(_MSG_SIN_LUGAR)

        primero: dict[str, Any] = cuerpo[0]
        latitud = _numero(primero.get("lat"))
        longitud = _numero(primero.get("lon"))
        if latitud is None or longitud is None:
            raise WeatherNotFound(_MSG_SIN_LUGAR)

        return Place(
            name=self._nombre_local(primero),
            country=_texto(primero.get("country")),
            latitude=latitud,
            longitude=longitud,
        )

    async def _clima(self, lugar: Place) -> CurrentWeather:
        """Coordenadas → clima actual, ya en unidades del dominio."""
        cuerpo = await self._get(
            _WEATHER_PATH,
            {
                "lat": f"{lugar.latitude}",
                "lon": f"{lugar.longitude}",
                "units": _UNITS,
                "lang": self._language,
            },
            contexto="clima",
        )
        if not isinstance(cuerpo, dict):
            raise WeatherUnavailable(_MSG_CAIDO, provider_message="respuesta sin objeto")

        principal: dict[str, Any] = cuerpo["main"] if isinstance(cuerpo.get("main"), dict) else {}
        viento: dict[str, Any] = cuerpo["wind"] if isinstance(cuerpo.get("wind"), dict) else {}

        temperatura = _numero(principal.get("temp"))
        if temperatura is None:
            # Un 200 sin temperatura es una respuesta incoherente, no un clima
            # desconocido: se trata como fallo del proveedor en vez de inventar
            # un 0 °C que el modelo contaría como cierto.
            raise WeatherUnavailable(_MSG_CAIDO, provider_message="respuesta sin main.temp")

        return CurrentWeather(
            place=lugar,
            temperature_c=round(temperatura, 1),
            feels_like_c=round(_numero(principal.get("feels_like")) or temperatura, 1),
            condition=_condicion(cuerpo),
            humidity_pct=int(_numero(principal.get("humidity")) or 0),
            wind_kph=round((_numero(viento.get("speed")) or 0.0) * _MS_A_KMH, 1),
            observed_at=_instante(cuerpo.get("dt")),
        )

    def _nombre_local(self, geocodificado: dict[str, Any]) -> str:
        """El nombre del lugar en el idioma configurado, si el proveedor lo trae.

        ``name`` viene en inglés o en transliteración ("Bogota", "Seville").
        ``local_names`` trae la versión de cada idioma y es lo que hace que la
        respuesta diga "Bogotá" y "Sevilla". No es cosmética: el modelo repite
        el nombre que le demos, y ver el destino escrito raro es justo la
        clase de detalle que hace que una respuesta suene a máquina.
        """
        locales = geocodificado.get("local_names")
        if isinstance(locales, dict):
            local = locales.get(self._language)
            if isinstance(local, str) and local:
                return local
        return _texto(geocodificado.get("name"))

    # --- Transporte ----------------------------------------------------------

    async def _get(self, path: str, params: dict[str, str], *, contexto: str) -> Any:
        """GET a la API con la key añadida, o una excepción de dominio.

        La ``appid`` se añade AQUÍ y en un solo sitio: ninguna ruta puede nacer
        sin ella por olvido, y ningún parámetro que venga de fuera puede
        pisarla (se escribe después del ``**params``).
        """
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                respuesta = await client.get(path, params={**params, "appid": self._api_key})
        except httpx.HTTPError as exc:
            logger.warning(
                "El proveedor de clima no respondió (%s): %s", contexto, type(exc).__name__
            )
            raise WeatherUnavailable(_MSG_CAIDO) from exc

        if respuesta.status_code == 404:
            # En el endpoint de clima un 404 es "no hay dato para ese punto".
            raise WeatherNotFound(_MSG_SIN_LUGAR, provider_status=404)
        if respuesta.status_code >= 400:
            raise self._error_http(respuesta, contexto=contexto)

        try:
            return respuesta.json()
        except ValueError as exc:
            logger.warning("El proveedor de clima devolvió un cuerpo ilegible (%s).", contexto)
            raise WeatherUnavailable(_MSG_CAIDO, provider_status=respuesta.status_code) from exc

    def _error_http(self, respuesta: httpx.Response, *, contexto: str) -> WeatherError:
        """Traduce un status de error a dominio, dejando la causa REAL en el log.

        El **401 tiene su propia línea de log** porque su causa más probable no
        es la que parece: una key de OpenWeatherMap recién creada tarda en
        activarse y responde 401 mientras tanto. Sin ese aviso, el síntoma
        ("Rover dice que no puede consultar el clima") manda a revisar el
        código en vez de a esperar diez minutos.
        """
        detalle = respuesta.text[:200]
        if respuesta.status_code in (401, 403):
            logger.error(
                "El proveedor de clima rechazó la key (%s, status=%s). Si la key es NUEVA, "
                "puede tardar un rato en activarse; si no, revisa ROVER_WEATHER_API_KEY. "
                "Detalle: %s",
                contexto,
                respuesta.status_code,
                detalle,
            )
        else:
            logger.warning(
                "El proveedor de clima falló (%s, status=%s): %s",
                contexto,
                respuesta.status_code,
                detalle,
            )
        return WeatherUnavailable(
            _MSG_CAIDO, provider_status=respuesta.status_code, provider_message=detalle
        )


# --- Parseo defensivo --------------------------------------------------------
# El cuerpo viene de un tercero: cada lectura asume que el campo puede faltar o
# venir con otro tipo. Un ``KeyError`` aquí sería un 500 en una conversación.


def _texto(valor: Any) -> str:
    return valor if isinstance(valor, str) else ""


def _numero(valor: Any) -> float | None:
    """Float, o ``None`` si el campo falta o no es numérico (``bool`` no cuenta)."""
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return None
    return float(valor)


def _condicion(cuerpo: dict[str, Any]) -> str:
    """La descripción del tiempo, ya traducida por el proveedor (``lang``)."""
    weather = cuerpo.get("weather")
    if isinstance(weather, list) and weather and isinstance(weather[0], dict):
        return _texto(weather[0].get("description"))
    return ""


def _instante(valor: Any) -> datetime | None:
    """``dt`` (epoch en segundos, UTC) → ``datetime``, o ``None`` si no viene."""
    segundos = _numero(valor)
    if segundos is None:
        return None
    try:
        return datetime.fromtimestamp(segundos, tz=UTC)
    except (OverflowError, OSError, ValueError):  # pragma: no cover - epoch absurdo
        return None
