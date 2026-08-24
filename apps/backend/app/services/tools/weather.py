"""La herramienta del clima: la primera concreta, y el molde de las que vengan.

Es la pieza que traduce entre dos mundos: por arriba, lo que el modelo puede
pedir (``get_weather`` con un ``location``); por abajo, el proveedor de clima
abstracto de ``services/weather``. **No sabe de OpenWeatherMap**: pide
``get_weather_provider()`` y usa los tipos de dominio. Esa es la razón por la
que el cambio a Open-Meteo no llega hasta aquí.

Lo que hay que copiar de este archivo al escribir la siguiente herramienta:

1. Un ``name`` corto en inglés y una ``description`` escrita **para el modelo**
   (cuándo usarla, no cómo funciona).
2. Un esquema de parámetros **mínimo**: cada campo opcional es una decisión más
   que el modelo puede equivocar.
3. Un ``run`` que llama a **una abstracción de proveedor**, no a una API, y
   traduce sus errores de dominio a ``ToolFailed`` con mensajes que el modelo
   pueda reformular.
4. Un resultado **recortado**, con las unidades en el nombre de la clave.
"""

from collections.abc import Mapping
from typing import Any

from app.services.tools.base import ToolFailed
from app.services.weather import (
    WeatherNotConfigured,
    WeatherNotFound,
    WeatherUnavailable,
    get_weather_provider,
)

#: Nombre con el que el modelo la pide. Corto, en inglés y con la forma
#: ``verbo_objeto`` que los modelos han visto un millón de veces: la
#: convención no es estética, es tasa de acierto.
TOOL_NAME = "get_weather"


class WeatherTool:
    """Consulta el clima actual de un lugar. Cumple el ``Protocol`` ``Tool``.

    Sin estado y sin dependencias en el constructor: resuelve el proveedor en
    cada ``run`` a través del registro. Así un test puede inyectar su doble
    (``set_weather_provider``) **después** de que el catálogo se haya armado,
    y el día que el proveedor se elija por región no habría que reconstruir
    nada.
    """

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        """Lo que el modelo lee para decidir si la llama.

        Dice el **caso de uso** y —esto importa tanto como lo anterior— el
        límite: es el clima de AHORA, no un pronóstico. Sin esa frase, un
        modelo servicial usa el dato de hoy para responder "¿qué tal el tiempo
        el sábado?", y el resultado es una invención con pinta de dato duro.
        """
        return (
            "Consulta el clima actual de una ciudad o lugar. Úsala cuando la persona "
            "pregunte por el tiempo, la temperatura o si va a llover en un destino, o "
            "cuando el clima de hoy sea relevante para una recomendación de viaje. "
            "Devuelve solo condiciones ACTUALES, no un pronóstico de días futuros."
        )

    @property
    def parameters(self) -> Mapping[str, Any]:
        """Esquema de argumentos: un lugar, y opcionalmente el país.

        ``location`` es lo único obligatorio. ``country_code`` existe porque los
        nombres de ciudad se repiten entre países (Cali, Córdoba, Santiago) y el
        modelo suele saber por el contexto de la conversación cuál es; cuando no
        lo sabe, lo omite y el resultado dice a qué país corresponde lo que
        encontró, que le permite avisar.

        No hay parámetro de fecha **a propósito**: el proveedor de hoy solo
        expone clima actual (ver ``services/weather/base.py``), y declarar un
        argumento que se ignora es la forma más fiable de que el modelo prometa
        un pronóstico que nadie va a consultar.
        """
        return {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": (
                        "Ciudad o lugar del que se quiere el clima, tal y como lo diría "
                        "una persona. Por ejemplo: 'Bogotá', 'Medellín', 'Ciudad de México'."
                    ),
                },
                "country_code": {
                    "type": "string",
                    "description": (
                        "Código de país ISO 3166-1 alfa-2 en mayúsculas ('CO', 'ES', 'MX'). "
                        "Opcional: úsalo solo si el nombre de la ciudad es ambiguo y sabes "
                        "por el contexto de qué país se habla."
                    ),
                },
            },
            "required": ["location"],
        }

    @property
    def status_label(self) -> str:
        return "Consultando el clima…"

    async def run(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Pide el clima al proveedor y devuelve un resultado limpio.

        Los tres errores de dominio se traducen a ``ToolFailed`` con mensajes
        **distintos**, porque llevan a conversaciones distintas: "no encontré
        el lugar" invita a que el modelo pida que se concrete; "el servicio no
        responde" invita a que responda con lo que sabe y lo diga. Colapsarlos
        en un "no pude" único tiraría esa diferencia justo donde se nota.
        """
        location = str(arguments["location"])
        country = arguments.get("country_code")
        country_code = str(country) if isinstance(country, str) and country.strip() else None

        try:
            clima = await get_weather_provider().current(location, country_code=country_code)
        except WeatherNotFound as exc:
            raise ToolFailed(
                f"No encontré ningún lugar llamado '{location}'. Pide que lo concreten "
                "(ciudad y país) o responde sin el dato del clima.",
                cause=str(exc),
            ) from exc
        except (WeatherUnavailable, WeatherNotConfigured) as exc:
            raise ToolFailed(
                "El servicio de clima no está disponible ahora mismo. Responde sin ese dato "
                "y dilo con naturalidad; no inventes una temperatura.",
                cause=f"{type(exc).__name__}: {exc}",
            ) from exc

        # Claves con la unidad DENTRO del nombre: es lo que impide que el
        # modelo lea 14 como grados Fahrenheit o el viento como m/s. Cuesta
        # tres caracteres de prompt y elimina una clase entera de error.
        resultado: dict[str, Any] = {
            "location": clima.place.label,
            "temperature_c": clima.temperature_c,
            "feels_like_c": clima.feels_like_c,
            "condition": clima.condition,
            "humidity_pct": clima.humidity_pct,
            "wind_kph": clima.wind_kph,
        }
        if clima.observed_at is not None:
            # ISO 8601 en UTC. El modelo no necesita el instante para redactar,
            # pero sí para no presentar como "ahora mismo" un dato de hace
            # horas si el proveedor viniera retrasado.
            resultado["observed_at"] = clima.observed_at.isoformat()
        return resultado
