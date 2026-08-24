"""Qué herramientas existen y cómo se le presentan al modelo.

Es el catálogo. El loop le pide dos cosas —"dame las declaraciones para el
modelo" y "dame la herramienta que se llama así"— y nadie más necesita
conocerlo. Añadir una herramienta es **una línea** en ``_catalogo_por_defecto``.


## Se ofrecen SIEMPRE, todas, en el mismo orden

El endpoint de chat no decide por petición qué herramientas mandar: manda el
catálogo entero en cada llamada y deja que el modelo elija. Tres razones:

1. **Filtrar exige un clasificador.** Adivinar "esta pregunta huele a clima"
   antes de llamar al modelo es o una lista de palabras clave (que falla con
   "¿me llevo chaqueta a Bogotá?") o **otra llamada a un modelo** — más
   latencia y más costo que la herramienta que se quería ahorrar.
2. **Rompería el prefijo estable.** Las definiciones viajan en el mismo cuerpo
   que el system prompt; un catálogo que cambia entre turnos cambia el prefijo
   y tira el caché automático de DeepSeek en cada llamada. La HU-2.2 midió 98 %
   de la entrada servida de caché con el prefijo estable: eso es lo que se
   estaría gastando.
3. **Con pocas herramientas no hay problema que resolver.** Lo que la
   investigación señala es la degradación con **catálogos grandes** (decenas de
   herramientas parecidas, donde el modelo confunde cuál toca). Con una, el
   modelo acierta; el costo de tenerla siempre declarada son unas decenas de
   tokens que además se sirven de caché.

Cuándo revisar esto: cuando el catálogo pase de ~10 herramientas, o cuando los
logs muestren llamadas a una herramienta en conversaciones que no iban de eso.
La revisión entonces no es filtrar por palabras clave, es **agrupar** (un
"buscador" que enruta por dentro) — y el sitio sería este archivo.

``specs()`` devuelve las declaraciones **ordenadas por nombre** por esa misma
razón: el orden de un ``dict`` es el de inserción, y un refactor que cambiara
el orden del catálogo invalidaría el caché sin que ningún test se pusiera rojo.


## Sin key del clima, la herramienta no se registra

``is_weather_configured()`` decide. Ofrecerle al modelo una herramienta que
solo puede fallar cuesta tokens en cada llamada para acabar en una degradación
evitable, y además le enseña a prometer un dato que no va a llegar. Es la misma
lógica que ``get_llm_provider(Capability.VISION)``: mejor que no exista a que
exista rota.
"""

import logging
from collections.abc import Iterable, Iterator

from app.services.llm import ToolSpec
from app.services.tools.base import Tool
from app.services.tools.weather import WeatherTool
from app.services.weather import is_weather_configured

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Las herramientas disponibles, por nombre.

    Objeto y no un diccionario de módulo: el loop recibe **una instancia**, así
    que un test puede darle un catálogo propio sin tocar estado global, y el
    día que las herramientas dependan del plan del usuario (Épica 5) el
    catálogo se construye por petición sin cambiar la firma de nadie.
    """

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        """Añade una herramienta. Un nombre repetido es un error, no un reemplazo.

        Registrar dos herramientas con el mismo nombre deja al modelo pidiendo
        una y ejecutándose otra —un fallo que se manifiesta como "la respuesta
        no tiene sentido", nunca como una excepción—, así que se corta aquí.
        """
        if tool.name in self._tools:
            raise ValueError(f"Ya hay una herramienta registrada con el nombre '{tool.name}'.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """La herramienta con ese nombre, o ``None`` si no existe.

        ``None`` y no una excepción porque **el caso normal del tool-calling es
        que el modelo se invente un nombre**: es el fallo típico, no una
        anomalía, y el loop lo convierte en un resultado que el modelo puede
        corregir. Ver ``loop.py``.
        """
        return self._tools.get(name)

    def specs(self) -> tuple[ToolSpec, ...]:
        """Las declaraciones para el modelo, **ordenadas por nombre**.

        El orden es parte del prefijo estable (ver el docstring del módulo), y
        por eso se fija aquí en vez de confiar en el orden de inserción.
        """
        return tuple(
            ToolSpec(name=tool.name, description=tool.description, parameters=tool.parameters)
            for _, tool in sorted(self._tools.items())
        )

    def names(self) -> tuple[str, ...]:
        """Los nombres registrados, ordenados. Para el mensaje de 'no existe'."""
        return tuple(sorted(self._tools))

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())


#: Catálogo inyectado (tests, o un futuro catálogo por plan). ``None`` = el de
#: por defecto.
_registro: ToolRegistry | None = None


def _catalogo_por_defecto() -> ToolRegistry:
    """Arma el catálogo con lo que esté configurado. **Aquí se añaden las nuevas.**"""
    registro = ToolRegistry()
    if is_weather_configured():
        registro.register(WeatherTool())
    else:
        logger.warning(
            "La herramienta del clima no se registra: falta ROVER_WEATHER_API_KEY. "
            "Rover conversará sin datos del tiempo (ver .env.example)."
        )
    return registro


def get_tool_registry() -> ToolRegistry:
    """El catálogo de herramientas de esta petición.

    Se construye en cada llamada en vez de cachearse en un global, y no es un
    descuido: construirlo es instanciar un par de objetos sin estado —más
    barato que la invalidación que haría falta— y así un cambio de
    configuración (o un doble inyectado a mitad de un test) se ve de inmediato
    sin que nadie tenga que acordarse de resetear nada.
    """
    return _registro if _registro is not None else _catalogo_por_defecto()


def set_tool_registry(registry: ToolRegistry) -> None:
    """Sustituye el catálogo. Para tests, y para el catálogo por plan del futuro."""
    global _registro
    _registro = registry


def reset_tool_registry() -> None:
    """Vuelve al catálogo por defecto (aislamiento entre tests)."""
    global _registro
    _registro = None
