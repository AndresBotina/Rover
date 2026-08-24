"""Herramientas del agente: la maquinaria de tool-calling y el catálogo (HU-2.6).

Es lo que le da a Rover **datos que su modelo no tiene**. La primera es el
clima; las siguientes (lugares, búsqueda web) son repeticiones del mismo molde.

Cómo se usa desde el endpoint de chat:

    from app.services.tools import ToolLoop, TextDelta, ToolStatus, get_tool_registry

    loop = ToolLoop(provider, registry=get_tool_registry(), system_prompt=PROMPT)
    async for evento in loop.run(contexto):
        ...                      # TextDelta → al cliente; ToolStatus → estado
    loop.steps                   # pasos intermedios, para persistir (NO exponer)

Añadir una herramienta nueva son **dos pasos**, y ninguno toca el loop:

1. Escribir una clase que cumpla el ``Protocol`` ``Tool`` (``base.py``);
   ``weather.py`` es el ejemplo a copiar.
2. Registrarla en ``_catalogo_por_defecto`` (``registry.py``).

Mapa de los módulos:

- ``base.py``     — el ``Protocol`` ``Tool``, ``ToolFailed`` y el parseo/validación
                    de los argumentos que manda el modelo.
- ``registry.py`` — qué herramientas existen y cómo se declaran al modelo.
- ``loop.py``     — el loop: preguntar, ejecutar, volver a preguntar.
- ``weather.py``  — la primera herramienta concreta (sobre ``services/weather``).
"""

from app.services.tools.base import ArgumentError, Tool, ToolFailed, parse_arguments
from app.services.tools.loop import (
    STATUS_ERROR,
    STATUS_INVALID_ARGUMENTS,
    STATUS_OK,
    STATUS_UNKNOWN_TOOL,
    TextDelta,
    ToolLoop,
    ToolStatus,
    TurnEvent,
)
from app.services.tools.registry import (
    ToolRegistry,
    get_tool_registry,
    reset_tool_registry,
    set_tool_registry,
)
from app.services.tools.weather import TOOL_NAME as WEATHER_TOOL_NAME
from app.services.tools.weather import WeatherTool

__all__ = [
    "STATUS_ERROR",
    "STATUS_INVALID_ARGUMENTS",
    "STATUS_OK",
    "STATUS_UNKNOWN_TOOL",
    "WEATHER_TOOL_NAME",
    "ArgumentError",
    "TextDelta",
    "Tool",
    "ToolFailed",
    "ToolLoop",
    "ToolRegistry",
    "ToolStatus",
    "TurnEvent",
    "WeatherTool",
    "get_tool_registry",
    "parse_arguments",
    "reset_tool_registry",
    "set_tool_registry",
]
