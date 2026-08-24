"""Qué es una herramienta y cómo se valida lo que el modelo pide (HU-2.6).

Una herramienta es lo que le da a Rover **datos que su modelo no tiene**: el
clima de hoy, un lugar, una búsqueda. Este módulo define el molde. Añadir una
herramienta nueva es implementar ``Tool`` y registrarla
(``registry.py``); **el loop no cambia** — ese es el objetivo del diseño y la
razón por la que la primera se construyó junto con la maquinaria y no dentro
de ella.


## El reparto de responsabilidades, y por qué es así

- ``Tool`` **se describe** (nombre, para qué sirve, qué argumentos admite) y
  **se ejecuta**. No sabe de modelos, ni de streaming, ni de JSON de cable.
- ``ToolRegistry`` (``registry.py``) sabe **cuáles hay** y las traduce a los
  ``ToolSpec`` que la capa de LLM le presenta al proveedor.
- ``ToolLoop`` (``loop.py``) orquesta: le pregunta al modelo, ejecuta lo que
  pida, le devuelve el resultado y vuelve a preguntar.

Las tres piezas se prueban por separado porque no se conocen entre sí más que
por estos tipos.


## ``run`` devuelve un diccionario, no un texto

Lo que sale de una herramienta es un **resultado estructurado y recortado**
(``{"lugar": "Bogotá, CO", "temperatura_c": 14.2, …}``), no la respuesta cruda
del servicio de turno. Dos razones, y la segunda pesa más que la primera:

1. **Tokens.** El JSON de una API del clima trae decenas de campos que a nadie
   le importan (identificadores internos, coordenadas con seis decimales,
   códigos de icono). Todo eso se paga como entrada en la llamada siguiente.
2. **Es contexto para un modelo, no un volcado.** Lo que el modelo hace con el
   resultado es tejerlo en una frase. Un objeto pequeño, con claves que se leen
   y unidades explícitas en el nombre (``temperatura_c``), produce respuestas
   mejores que un volcado donde el dato útil está enterrado.

Serializarlo a JSON para el cable es trabajo del loop: la herramienta devuelve
estructura, no cadenas.


## Los fallos se cuentan, no se lanzan hacia arriba

``ToolFailed`` es la forma que tiene una herramienta de decir "no pude, y esto
es lo que le puedes contar al modelo". Su mensaje viaja al modelo como
resultado de la llamada, y por eso está escrito para que un modelo lo entienda
y lo reformule ("no encontré ningún lugar con ese nombre"), no para que un
humano lo vea tal cual.

Una excepción inesperada de una herramienta **tampoco** tumba la conversación:
el loop la captura, la loguea con traza y la convierte en el mismo resultado
degradado. La diferencia es que ``ToolFailed`` es un fallo PREVISTO —y su
mensaje está pensado— mientras que lo otro es un bug que además hay que ver en
el log.


## La validación de argumentos, sin dependencia nueva

``validate_arguments`` comprueba lo que de verdad falla en la práctica: que el
JSON sea parseable, que sea un objeto, que estén los campos obligatorios y que
los tipos declarados cuadren. **No** es un validador de JSON Schema completo
(no hay ``enum``, ni ``minimum``, ni ``$ref``), y es deliberado: los esquemas
de estas herramientas los escribimos nosotros y caben en diez líneas, así que
un validador completo sería traer una dependencia —y su superficie— para
sustituir cuatro ``if``. Está en UNA función para que el día que los esquemas
crezcan, cambiarla por ``jsonschema`` sea reemplazar su cuerpo.

Lo que NO hace, a propósito: rechazar campos de más. Un modelo que añade un
argumento que no pedimos está siendo generoso, no incorrecto, y romper la
llamada por eso gastaría una vuelta entera del loop para nada; el campo
sobrante se ignora al ejecutar.
"""

import json
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

#: Tipos de JSON Schema que se saben comprobar → tipos de Python aceptables.
#: ``int`` vale donde se pide ``number`` (todo entero es un número), pero no al
#: revés. ``bool`` se excluye de los numéricos: en Python es un ``int``, y un
#: ``true`` donde se esperaba una temperatura es un error, no un 1.
_TIPOS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


class ToolFailed(Exception):
    """La herramienta no pudo hacer su trabajo, y sabe qué contar de ello.

    El mensaje se le entrega **al modelo** como resultado de la llamada, así
    que se escribe en lenguaje natural y sin jerga de infraestructura: es
    materia prima para una frase como "no pude mirar el clima ahora mismo,
    pero…". Nunca lleva status HTTP, URLs, nombres de proveedor ni keys.

    ``cause`` es el diagnóstico técnico para el LOG. Va aparte justamente para
    que no haya forma de mandarlo por error hacia arriba: son dos campos
    distintos, con dos destinos distintos.
    """

    def __init__(self, message: str, *, cause: str | None = None) -> None:
        super().__init__(message)
        self.cause = cause


@runtime_checkable
class Tool(Protocol):
    """Una herramienta que el modelo puede pedir.

    ``Protocol`` y no una clase base: una herramienta no tiene que heredar de
    nada ni importar este módulo para cumplir el contrato, y un doble de test
    es una clase de quince líneas. Mismo criterio que ``LLMProvider`` (HU-2.1)
    y ``RateLimitStore`` (HU-1.7).

    ``runtime_checkable`` para que los tests puedan afirmar el contrato con un
    ``isinstance``; comprueba la presencia de los miembros, no sus firmas, que
    es de lo que se encarga mypy.
    """

    @property
    def name(self) -> str:
        """Identificador que el modelo usa para pedirla.

        Va al prompt en cada llamada, así que es corto y en inglés
        (``get_weather``): es la convención que los modelos han visto un millón
        de veces en su entrenamiento, y desviarse de ella sin ganar nada
        empeora la tasa de acierto.
        """
        ...

    @property
    def description(self) -> str:
        """Para qué sirve y CUÁNDO usarla. Es prompt, no documentación.

        Es el texto con el que el modelo decide llamarla o no, y por tanto la
        pieza que más determina si la maquinaria funciona bien. Se escribe
        diciendo el caso de uso ("cuando el usuario pregunte por el tiempo…"),
        no la implementación.
        """
        ...

    @property
    def parameters(self) -> Mapping[str, Any]:
        """Los argumentos, como **JSON Schema** (un objeto ``type: object``).

        JSON Schema y no un lenguaje propio: es lo que entienden todas las APIs
        de function-calling, así que inventarse otro formato sería traducir dos
        veces para acabar en el mismo sitio.
        """
        ...

    @property
    def status_label(self) -> str:
        """Frase que ve el usuario mientras se ejecuta ("Consultando el clima…").

        Vive en la herramienta y no en el loop porque es lo único de la fase de
        ejecución que sale al cliente, y quien sabe cómo llamarla en cristiano
        es quien la escribió. Nunca incluye argumentos: ver ``loop.py``.
        """
        ...

    async def run(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Ejecuta la herramienta y devuelve el resultado ya recortado.

        ``arguments`` llega **ya parseado y validado** contra ``parameters``:
        los obligatorios están y los tipos cuadran. Puede traer campos de más
        (ver el docstring del módulo), que se ignoran.

        Levanta ``ToolFailed`` cuando no puede cumplir. Cualquier otra
        excepción la captura el loop y la trata igual, pero además la loguea
        como bug.
        """
        ...


class ArgumentError(Exception):
    """Lo que el modelo mandó como argumentos no sirve.

    Su mensaje se le devuelve **al modelo** para que corrija en la vuelta
    siguiente: "el argumento 'location' es obligatorio" es accionable para él,
    mientras que un "argumentos inválidos" a secas solo le deja adivinar. Es la
    diferencia entre una vuelta más del loop y una respuesta degradada.
    """


def parse_arguments(crudos: str, esquema: Mapping[str, Any]) -> dict[str, Any]:
    """Cadena JSON del modelo → diccionario validado contra el esquema.

    ``crudos`` viene tal cual lo emitió el modelo (ver ``ToolCall.arguments``),
    así que lo primero es asumir que puede no ser JSON: es el fallo más común
    del tool-calling después de inventarse el nombre de la herramienta.

    Una cadena **vacía** se trata como ``{}`` y no como error: es lo que emiten
    varios proveedores para una herramienta sin argumentos obligatorios, y
    rechazarlo haría fallar el caso más simple que existe.
    """
    texto = crudos.strip()
    if not texto:
        argumentos: Any = {}
    else:
        try:
            argumentos = json.loads(texto)
        except ValueError as exc:
            raise ArgumentError(
                "Los argumentos no son JSON válido. Vuelve a llamar a la herramienta "
                "con un objeto JSON bien formado."
            ) from exc

    if not isinstance(argumentos, dict):
        raise ArgumentError("Los argumentos deben ser un objeto JSON, no un valor suelto.")

    validate_arguments(argumentos, esquema)
    return argumentos


def validate_arguments(argumentos: Mapping[str, Any], esquema: Mapping[str, Any]) -> None:
    """Comprueba obligatorios y tipos. Levanta ``ArgumentError`` con el porqué.

    Subconjunto deliberado de JSON Schema — ver el docstring del módulo para
    qué cubre, qué no, y por qué no se trae una dependencia para esto.
    """
    propiedades = esquema.get("properties")
    propiedades = propiedades if isinstance(propiedades, dict) else {}

    obligatorios = esquema.get("required")
    obligatorios = obligatorios if isinstance(obligatorios, list) else []

    faltantes = [
        nombre
        for nombre in obligatorios
        if isinstance(nombre, str) and argumentos.get(nombre) is None
    ]
    if faltantes:
        lista = ", ".join(f"'{nombre}'" for nombre in faltantes)
        raise ArgumentError(f"Faltan argumentos obligatorios: {lista}.")

    for nombre, valor in argumentos.items():
        definicion = propiedades.get(nombre)
        if not isinstance(definicion, dict) or valor is None:
            # Campo que no declaramos (se ignora) o nulo explícito en un campo
            # opcional (equivale a no mandarlo).
            continue
        esperados = _TIPOS.get(definicion.get("type", ""))
        if esperados is None:
            continue
        if isinstance(valor, bool) and bool not in esperados:
            raise ArgumentError(f"El argumento '{nombre}' debe ser de tipo {definicion['type']}.")
        if not isinstance(valor, esperados):
            raise ArgumentError(f"El argumento '{nombre}' debe ser de tipo {definicion['type']}.")
