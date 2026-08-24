"""Quién sirve el clima: **el único archivo que hay que tocar para cambiarlo**.

Es el *seam* de proveedor de clima, calcado del de LLM (``llm/registry.py``) y
por la misma razón: el resto del backend pide ``get_weather_provider()`` y
jamás construye una implementación a mano. Esa disciplina es lo que hace que
el cambio de proveedor sea local.


## El punto de cambio a Open-Meteo, en concreto

Cambiar OpenWeatherMap por Open-Meteo —que **no necesita key**— es reemplazar
el cuerpo de ``_construir_proveedor()``:

    from app.services.weather.openmeteo import OpenMeteoProvider

    def _construir_proveedor() -> WeatherProvider:
        return OpenMeteoProvider(language=settings.weather_language)

y escribir ese ``openmeteo.py`` cumpliendo el ``Protocol`` de ``base.py``. Eso
es todo. No se toca el loop de tool-calling, ni ``services/tools/weather.py``
(la definición que ve el modelo), ni el endpoint, ni ninguno de los tests del
ciclo: **ninguno importa el módulo del proveedor**. El único que lo hace es
este archivo, y esa es justamente la propiedad que se está comprando.

Ver el docstring de ``openweathermap.py`` para por qué se eligió ese hoy.


## ``is_weather_configured`` y por qué existe

El catálogo de herramientas la consulta para decidir si registra la del clima
(``services/tools/registry.py``). Sin key, la herramienta **no se le ofrece al
modelo**: ofrecer una que solo puede fallar es gastar tokens del prompt en cada
llamada para acabar en una degradación evitable. Con Open-Meteo esta función
pasaría a devolver ``True`` siempre — otra señal de que la key es un detalle
del proveedor y no del diseño.
"""

import logging

from app.core.config import settings
from app.services.weather.base import WeatherNotConfigured, WeatherProvider
from app.services.weather.openweathermap import OpenWeatherMapProvider

logger = logging.getLogger(__name__)

#: Proveedor ya construido, o inyectado por un test. Perezoso: construirlo al
#: importar exigiría la key para arrancar la app.
_proveedor: WeatherProvider | None = None


def _construir_proveedor() -> WeatherProvider:
    """Arma el proveedor con lo que diga la config. **El punto de cambio.**

    Único sitio del código que lee la configuración del clima, igual que
    ``_construir_proveedor_de_texto`` con la del LLM.
    """
    if settings.weather_api_key is None:
        raise WeatherNotConfigured(
            "El proveedor de clima no está configurado (falta ROVER_WEATHER_API_KEY); "
            "ver .env.example."
        )
    return OpenWeatherMapProvider(
        api_key=settings.weather_api_key.get_secret_value(),
        base_url=settings.weather_base_url,
        language=settings.weather_language,
        timeout_seconds=settings.weather_timeout_seconds,
    )


def is_weather_configured() -> bool:
    """Si hay con qué consultar el clima (config o proveedor inyectado).

    No construye nada: se llama al armar el catálogo de herramientas, que
    ocurre en cada petición de chat.
    """
    return _proveedor is not None or settings.weather_api_key is not None


def get_weather_provider() -> WeatherProvider:
    """El proveedor de clima, construyéndolo la primera vez."""
    global _proveedor
    if _proveedor is None:
        _proveedor = _construir_proveedor()
    return _proveedor


def set_weather_provider(provider: WeatherProvider) -> None:
    """Registra (o sustituye) el proveedor. Para tests y para el día del cambio."""
    global _proveedor
    _proveedor = provider


def reset_weather_provider() -> None:
    """Olvida el proveedor construido (aislamiento entre tests)."""
    global _proveedor
    _proveedor = None
