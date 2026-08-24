"""Contrato del proveedor de clima: tipos de dominio, errores e interfaz.

Este módulo es el **único** que el resto del backend necesita conocer para
saber qué tiempo hace en un sitio. No importa nada de OpenWeatherMap, ni de
Open-Meteo, ni de httpx: lo que hay detrás se elige en ``registry.py`` y se
implementa en un módulo aparte (``openweathermap.py``). Es la misma jugada que
``LLMProvider`` en la HU-2.1 y que ``RateLimitStore`` en la HU-1.7 — la
interfaz es lo estable, la implementación es lo desechable.


## Una sola operación, y la geocodificación DENTRO

``current(location)`` recibe un **nombre de lugar** ("Bogotá", "Medellín,
Colombia") y devuelve el clima. Que OpenWeatherMap necesite coordenadas y haya
que geocodificar primero es **problema suyo**, no del llamador: son dos
llamadas HTTP encadenadas que viven dentro de la implementación.

Eso no es comodidad, es lo que hace posible el cambio de proveedor. Si la
interfaz fuera ``geocode(nombre) -> coords`` + ``weather(coords)``, estaría
copiando la forma de la API de OpenWeatherMap y el día que otro proveedor
resolviera el nombre en una sola llamada —o en tres— habría que reescribir a
quien las orquesta. Con una operación, el proveedor decide cuántos viajes hace.


## Por qué los errores son TRES y no uno

- ``WeatherNotFound`` — el lugar no existe o no se pudo resolver. Es
  información **útil para el modelo**: puede pedir que se concrete el sitio.
- ``WeatherUnavailable`` — el proveedor no respondió (caído, timeout, sin
  cuota, key todavía sin activar). El lugar puede existir perfectamente; lo que
  falla es nuestro lado.
- ``WeatherNotConfigured`` — falta la key. Es un error de **operación**, no de
  la petición.

Colapsarlos en un "no pude" único perdería justo la distinción que hace que la
respuesta degradada sea buena: "no encontré ese lugar, ¿me lo concretas?" y
"el servicio del clima no responde ahora mismo" son dos conversaciones
distintas. El mensaje de la excepción es **seguro** para dárselo al modelo; el
diagnóstico crudo del proveedor se queda en el log, igual que en ``llm/errors``.


## Lo que esta interfaz todavía NO tiene, y dónde entraría

**Pronóstico** (mañana, este fin de semana, un rango de fechas). Hoy solo hay
clima actual, porque es lo que valida la maquinaria de la HU-2.6 con la
superficie más pequeña. Cuando haga falta, la extensión es **un método más
aquí** (``forecast(location, *, days)``) con su tipo de dominio, no un rediseño:
tanto OpenWeatherMap como Open-Meteo lo sirven, y la herramienta ganaría un
parámetro de fecha sin que el loop se entere.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class WeatherError(Exception):
    """Fallo consultando el clima, ya traducido a dominio.

    El **mensaje** (``str(exc)``) es seguro: describe qué pasó sin nombrar al
    proveedor, sin URLs y por supuesto sin la key. El diagnóstico crudo (status
    HTTP, cuerpo del error) viaja en ``provider_status``/``provider_message`` y
    es SOLO para los logs del servidor — mismo contrato que ``LLMError``.
    """

    def __init__(
        self,
        message: str,
        *,
        provider_status: int | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_status = provider_status
        self.provider_message = provider_message


class WeatherNotFound(WeatherError):
    """No se pudo resolver el lugar pedido a un punto del mapa.

    No es un fallo del servicio: es una pregunta que no se puede contestar tal
    y como está formulada ("el clima en el barrio de mi tía"). Quien la reciba
    puede pedir que se concrete.
    """


class WeatherUnavailable(WeatherError):
    """El proveedor no entregó el dato: caído, lento, sin cuota o key inactiva.

    Incluye a propósito el **401 por key recién creada**: en OpenWeatherMap una
    key nueva tarda un rato en activarse y responde 401 mientras tanto. Desde
    fuera es indistinguible de una key revocada, y en los dos casos lo que toca
    es lo mismo —degradar y dejar la causa real en el log—, así que no merecen
    tipos distintos.
    """


class WeatherNotConfigured(WeatherError):
    """Falta la configuración del proveedor (típicamente ``ROVER_WEATHER_API_KEY``).

    Error de despliegue, no de la petición. En la práctica casi no se ve: sin
    key, la herramienta del clima **ni siquiera se registra** (ver
    ``services/tools/registry.py``), así que el modelo no puede pedirla. Existe
    para el borde en que la key desaparece con el proceso ya arrancado.
    """


@dataclass(frozen=True, slots=True)
class Place:
    """Un lugar ya resuelto a un punto del mapa.

    ``name`` y ``country`` no son adorno: son la forma de que la respuesta
    pueda decir **qué** lugar se consultó. "Cali" resuelve a Colombia, pero
    también hay un Cali en Perú y otro en Filipinas; sin el país en el
    resultado, el modelo no puede avisar de que quizá acertó con el sitio
    equivocado.
    """

    name: str
    #: ISO 3166-1 alfa-2 ("CO", "ES"). Vacío si el proveedor no lo reporta.
    country: str
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        """Nombre legible para enseñarle al modelo ("Bogotá, CO")."""
        return f"{self.name}, {self.country}" if self.country else self.name


@dataclass(frozen=True, slots=True)
class CurrentWeather:
    """El clima de ahora mismo en un lugar, en unidades del SISTEMA MÉTRICO.

    Las unidades son parte del **contrato de dominio** y no configuración: un
    campo ``temperature`` cuyo significado dependiera de una variable de
    entorno obligaría a cada lector —el modelo incluido— a preguntarse en qué
    escala está. ``temperature_c`` no admite dos lecturas. Convertir a otra
    escala es cosa de quien presenta, no de quien mide.

    ``condition`` es texto libre del proveedor ya traducido al idioma que se
    le pidió ("nubes dispersas"). No se normaliza a un enum propio: el
    consumidor es un modelo de lenguaje, que teje mejor una frase natural que
    una constante, y un enum obligaría a mapear el catálogo entero de cada
    proveedor para no perder matices.
    """

    place: Place
    temperature_c: float
    feels_like_c: float
    condition: str
    humidity_pct: int
    wind_kph: float
    #: Momento de la observación según el proveedor, en UTC. ``None`` si no lo
    #: reporta: es un dato que se REGALA, no algo que el contrato garantice.
    observed_at: datetime | None = None


class WeatherProvider(Protocol):
    """Lo que Rover necesita de "un servicio de clima". Nada más.

    Se implementa por ESTRUCTURA (``Protocol``, no herencia): una
    implementación no tiene que importar este módulo para cumplirlo y un doble
    de test es una clase de diez líneas. Mismo criterio que ``LLMProvider``.
    """

    @property
    def name(self) -> str:
        """Identificador del servicio que hay detrás (para logs)."""
        ...

    async def current(self, location: str, *, country_code: str | None = None) -> CurrentWeather:
        """El clima actual de ``location``, resolviendo el nombre por dentro.

        ``country_code`` (ISO 3166-1 alfa-2) desambigua cuando el nombre se
        repite en varios países. Es opcional porque quien llama —en última
        instancia, un modelo de lenguaje leyendo una frase— casi nunca lo
        tiene, y exigirlo convertiría "¿qué tal el clima en Roma?" en un error.

        Levanta ``WeatherNotFound``, ``WeatherUnavailable`` o
        ``WeatherNotConfigured``: nunca un error del proveedor ni del cliente
        HTTP.
        """
        ...


def clean_location(location: str) -> str:
    """Normaliza el nombre de un lugar antes de mandarlo a geocodificar.

    Colapsa espacios y recorta. Está aquí y no en la implementación porque es
    higiene del DOMINIO —el texto lo escribe un modelo y llega con saltos de
    línea o espacios de más con una frecuencia incómoda— y cualquier proveedor
    futuro la necesita igual.
    """
    return " ".join(location.split())


def format_place(nombres: Sequence[str]) -> str:
    """Une las partes de un nombre de lugar sin dejar comas huérfanas."""
    return ", ".join(parte for parte in nombres if parte)
