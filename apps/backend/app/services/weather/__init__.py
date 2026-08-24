"""Clima en vivo, tras su propia abstracción (HU-2.6).

Rover no habla con OpenWeatherMap: habla con **un proveedor de clima** en
abstracto. Misma jugada que ``services/llm`` con DeepSeek, y con la misma
promesa — cambiar a Open-Meteo (que no necesita key) es escribir una clase y
cambiar una línea de ``registry.py``, sin tocar el agente.

Cómo se usa, siempre así y nunca importando ``openweathermap``:

    from app.services.weather import get_weather_provider

    clima = await get_weather_provider().current("Bogotá")
    clima.temperature_c, clima.condition, clima.place.label

Mapa de los módulos:

- ``base.py``            — tipos de dominio, errores y el ``Protocol``.
- ``openweathermap.py``  — implementación concreta (geocoding + clima).
- ``registry.py``        — quién sirve el clima; **el punto de cambio**.
"""

from app.services.weather.base import (
    CurrentWeather,
    Place,
    WeatherError,
    WeatherNotConfigured,
    WeatherNotFound,
    WeatherProvider,
    WeatherUnavailable,
)
from app.services.weather.registry import (
    get_weather_provider,
    is_weather_configured,
    reset_weather_provider,
    set_weather_provider,
)

__all__ = [
    "CurrentWeather",
    "Place",
    "WeatherError",
    "WeatherNotConfigured",
    "WeatherNotFound",
    "WeatherProvider",
    "WeatherUnavailable",
    "get_weather_provider",
    "is_weather_configured",
    "reset_weather_provider",
    "set_weather_provider",
]
