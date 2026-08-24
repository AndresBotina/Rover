"""El loop de tool-calling: preguntar, ejecutar, volver a preguntar (HU-2.6).

Es la maquinaria. El modelo recibe el contexto **y las herramientas
disponibles**; si decide llamar a alguna, devuelve la petición en vez del texto
final; el backend la ejecuta y le devuelve el resultado como un turno más; el
modelo redacta entonces la respuesta, que sale por streaming hacia el cliente.

Lo que este módulo NO sabe: qué herramientas existen (eso es ``registry.py``),
qué hace cada una (``base.Tool``), ni cómo se serializa un evento SSE (eso es
``api/sse.py``). Por eso añadir una herramienta no lo toca.


## Cero, una o varias llamadas

Los tres casos son el mismo código:

- **Cero** — el modelo responde directo. El stream de la primera vuelta trae
  texto y ninguna petición, el loop sale y la conversación se comporta
  exactamente como antes de esta HU. Es el camino de la mayoría de los turnos.
- **Una** — vuelta 1 pide, se ejecuta, vuelta 2 redacta.
- **Varias** — el modelo puede pedir dos herramientas **en la misma vuelta**
  (se ejecutan en orden y cada resultado vuelve con el ``tool_call_id`` de su
  petición), o pedir una, ver el resultado y pedir otra en la vuelta siguiente.


## El límite de vueltas, y qué pasa al llegar

``ROVER_TOOL_LOOP_MAX_ITERATIONS`` (por defecto **3**) es el número máximo de
llamadas al modelo en un turno. Con las herramientas de hoy, el camino normal
gasta 2 (pedir → redactar); la tercera existe para el caso legítimo de
encadenar —consultar el clima de una ciudad, ver que el usuario preguntaba por
dos, consultar la otra— sin dejar sitio a que un modelo terco se quede en
bucle.

El límite no es una defensa contra un cuelgue: es una defensa contra el
**costo**. Cada vuelta es una llamada facturada con un contexto que además
CRECE (arrastra la petición y el resultado de la anterior), así que un loop
descontrolado no se nota como lentitud sino como una factura. Tres vueltas
acotan el peor caso de un turno a algo que se puede razonar.

Y al llegar al límite **no se corta la conversación**: la última vuelta se hace
**sin ofrecer herramientas**, así que el modelo no tiene más opción que
redactar en prosa con lo que ya tiene. Es la diferencia entre "el usuario
recibe una respuesta escrita con datos incompletos" y "el usuario recibe un
error" — y no cuesta nada, porque esa llamada había que hacerla igual.


## Qué ve el cliente mientras se ejecuta una herramienta

Un evento de **estado** (``ToolStatus``) con el nombre de la herramienta y una
frase hecha ("Consultando el clima…"). Nunca los argumentos ni el resultado.

Se decidió emitirlo en vez de no emitir nada porque la fase de herramienta abre
un **silencio de varios segundos** —una llamada al modelo que no imprime nada,
más una llamada HTTP a un tercero— justo en un producto cuya promesa es ver el
texto aparecer palabra a palabra. Sin señal, esa pausa es indistinguible de un
cuelgue, y la reacción natural es recargar (que además tira la respuesta que
venía en camino).

Lo que **no** viaja, y por qué:

- **Los argumentos.** Los escribe el modelo y pueden traer una interpretación
  equivocada de la pregunta; enseñarlos convierte un detalle interno en algo
  que el usuario tiene que juzgar.
- **El resultado.** Es la respuesta cruda de un tercero. La decisión de la
  épica es que solo sale texto conversacional (ver ``models/conversation.py``).
- **El estado de una herramienta que no existe.** Si el modelo se inventa un
  nombre, el cliente no se entera: anunciar "consultando fantasía…" sería
  exponer una alucinación como si fuera una capacidad del producto.

El contrato del stream gana un tipo de evento (``status`` en ``@rover/shared``),
y los clientes viejos no se rompen: su type guard es estricto y descarta lo que
no conoce, así que un evento nuevo se ignora en vez de romper el parseo.


## Los fallos: TODA petición se contesta, siempre

Herramienta que no existe, argumentos que no son JSON, API caída, bug nuestro:
los cuatro terminan igual, en un **mensaje de rol ``tool``** que le cuenta al
modelo qué pasó, para que lo maneje él. Nunca se aborta el turno.

Que sea *siempre* no es solo elegancia: el formato de cable lo **exige**. Si el
turno del asistente viaja con tres ``tool_calls`` y solo se contestan dos, el
proveedor responde **400** y se cae toda la conversación — un fallo de una
herramienta se habría convertido en un fallo del chat, que es exactamente lo
que esta HU existe para evitar.

Devolverle el error al modelo en vez de degradar por nuestra cuenta con una
frase enlatada es la decisión importante, y se toma por tres motivos:

1. **La personalidad ya sabe hacerlo.** El prompt de Rover (HU-2.2) le pide ser
   honesto cuando no tiene un dato; con el error en la mano, escribe "no pude
   mirar el clima ahora mismo, pero en Bogotá en esta época…" en el tono de la
   conversación y en su idioma.
2. **El turno no era solo la herramienta.** "¿Qué hago en Medellín y qué tal el
   tiempo?" merece la mitad que sí se puede contestar. Una frase enlatada la
   tiraría entera.
3. **A veces el error es corregible.** "No encontré ningún lugar llamado X" le
   permite reintentar con el nombre bien escrito, que es una vuelta más del
   loop y una respuesta buena en vez de una excusa.

La causa REAL —status del proveedor, traza si fue un bug— va al log del
servidor y a ``tool_steps``; al modelo solo le llega una frase segura.
"""

import json
import logging
import time
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.llm import (
    LLMProvider,
    Message,
    Role,
    ToolCall,
    ToolCallAccumulator,
)
from app.services.tools.base import ArgumentError, Tool, ToolFailed, parse_arguments
from app.services.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: Logger dedicado a la ejecución de herramientas, en la misma línea que
#: ``app.llm``: una línea por ejecución, todas con las mismas claves ``tool_``,
#: aislable con un solo filtro. Es la serie con la que se responderá "¿cuánto
#: falla el clima?" sin leer conversaciones.
tool_logger = logging.getLogger("app.tools")

#: Cómo terminó la ejecución de una petición del modelo. Son los valores que
#: quedan en ``tool_steps``, así que forman un vocabulario cerrado y agregable.
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_UNKNOWN_TOOL = "unknown_tool"
STATUS_INVALID_ARGUMENTS = "invalid_arguments"


@dataclass(frozen=True, slots=True)
class TextDelta:
    """Texto nuevo para el usuario. El delta, no el acumulado."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """Aviso de que se está ejecutando una herramienta.

    Solo nombre y etiqueta: ver el docstring del módulo para lo que
    deliberadamente NO lleva.
    """

    tool: str
    label: str


#: Lo que sale del loop hacia el endpoint. Unión y no una clase con un campo
#: ``tipo``: quien la consume ramifica con ``isinstance`` y mypy le exige
#: cubrir los dos casos, que es justo lo que se quiere de un contrato que va a
#: crecer.
TurnEvent = TextDelta | ToolStatus


class ToolLoop:
    """Un turno del agente: llamadas al modelo, ejecuciones y pasos intermedios.

    Objeto y no una función suelta porque el turno produce **dos** cosas: el
    flujo de eventos (que se consume mientras ocurre) y los ``tool_steps`` (que
    se leen al final, para persistirlos). Devolver ambas desde un generador
    obligaría a mezclar en el mismo flujo lo que sale al cliente con lo que no
    debe salir nunca — exactamente la confusión que la HU-2.3 quiso evitar
    poniéndolos en columnas distintas.

    De usar y tirar: uno por turno. ``steps`` se lee **después** de agotar
    ``run``.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        registry: ToolRegistry,
        system_prompt: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._system_prompt = system_prompt
        self._max_iterations = (
            settings.tool_loop_max_iterations if max_iterations is None else max_iterations
        )
        self._steps: list[dict[str, Any]] = []

    @property
    def steps(self) -> list[dict[str, Any]]:
        """Los pasos intermedios del turno, en orden, listos para ``tool_steps``.

        **INTERNO**: se persiste en la fila del mensaje del asistente y no se
        expone al cliente ni se reenvía al contexto de turnos siguientes
        (decisión cerrada de la HU-2.5, con sus tres razones en
        ``services/chat.build_context``).

        Lista vacía cuando el turno no usó herramientas, que es lo mismo que
        tiene por defecto la columna: una sola forma de decir "aquí no hubo
        herramientas".
        """
        return self._steps

    @property
    def used_tools(self) -> bool:
        """Si el turno llegó a pedir alguna herramienta."""
        return bool(self._steps)

    async def run(self, messages: Sequence[Message]) -> AsyncGenerator[TurnEvent]:
        """Ejecuta el turno completo y va emitiendo lo que el cliente puede ver.

        ``messages`` es el contexto ya armado (``services/chat.build_context``):
        historial recortado + mensaje nuevo. El system prompt va aparte, como
        siempre (HU-2.1).

        Los errores del proveedor (``LLMError``) **suben tal cual**: quien sabe
        traducirlos a un status HTTP o a un evento SSE de error es el endpoint,
        y el loop no tiene por qué conocer HTTP. Los errores de las
        herramientas, en cambio, no salen nunca de aquí.
        """
        contexto = list(messages)

        for vuelta in range(1, self._max_iterations + 1):
            # La ÚLTIMA vuelta va sin herramientas: sin nada que pedir, al
            # modelo solo le queda redactar. Ver el docstring del módulo.
            ultima = vuelta == self._max_iterations
            tools = None if ultima else self._registry.specs()
            if ultima and vuelta > 1:
                logger.warning(
                    "El turno alcanzó el límite de %s vueltas del loop de herramientas; "
                    "la última llamada va sin tools para forzar una respuesta.",
                    self._max_iterations,
                )

            acumulador = ToolCallAccumulator()
            texto: list[str] = []

            async with aclosing(
                self._provider.stream(contexto, system_prompt=self._system_prompt, tools=tools)
            ) as stream:
                async for trozo in stream:
                    if trozo.text:
                        texto.append(trozo.text)
                        yield TextDelta(trozo.text)
                    for fragmento in trozo.tool_calls:
                        acumulador.add(fragmento)

            llamadas = () if ultima else acumulador.result()
            if not llamadas:
                # Cero herramientas (o última vuelta): el modelo ya respondió.
                return

            # El turno del asistente que PIDIÓ entra al contexto tal cual, con
            # sus ``tool_calls``. Sin él, el mensaje de rol ``tool`` que viene
            # después no responde a nada y el proveedor devuelve 400.
            contexto.append(
                Message(role=Role.ASSISTANT, content="".join(texto), tool_calls=llamadas)
            )

            for llamada in llamadas:
                herramienta = self._registry.get(llamada.name)
                if herramienta is not None:
                    # El estado solo se anuncia para herramientas que EXISTEN:
                    # una alucinación del modelo no se le enseña al usuario.
                    yield ToolStatus(tool=herramienta.name, label=herramienta.status_label)
                resultado = await self._ejecutar(llamada, herramienta, vuelta=vuelta)
                contexto.append(Message(role=Role.TOOL, content=resultado, tool_call_id=llamada.id))

        # Inalcanzable: la última vuelta siempre sale por el ``return`` de
        # arriba, porque no se le ofrecen herramientas y ``llamadas`` es vacío.
        raise AssertionError("el loop de herramientas debe salir en la última vuelta")

    async def _ejecutar(self, llamada: ToolCall, tool: Tool | None, *, vuelta: int) -> str:
        """Ejecuta UNA petición del modelo y devuelve lo que se le contesta.

        Siempre devuelve una cadena JSON —resultado o error—: ver "TODA
        petición se contesta" en el docstring del módulo. Y siempre deja un
        paso en ``steps``, incluidas las peticiones que no se pudieron ni
        intentar, porque para depurar "el modelo se inventó una herramienta"
        hace falta ver justamente eso.
        """
        inicio = time.perf_counter()
        paso: dict[str, Any] = {
            "iteration": vuelta,
            "tool": llamada.name,
            "tool_call_id": llamada.id,
        }

        if tool is None:
            # El fallo típico del tool-calling. Se le contesta con la lista de
            # las que sí existen: es lo que le permite corregir en la vuelta
            # siguiente en vez de insistir con el mismo nombre inventado.
            disponibles = ", ".join(self._registry.names()) or "ninguna"
            mensaje = (
                f"No existe ninguna herramienta llamada '{llamada.name}'. "
                f"Herramientas disponibles: {disponibles}. "
                "Responde con lo que sepas o usa una de las disponibles."
            )
            logger.warning(
                "El modelo pidió una herramienta inexistente: %r (disponibles: %s).",
                llamada.name,
                disponibles,
            )
            return self._cerrar(paso, inicio, STATUS_UNKNOWN_TOOL, error=mensaje)

        try:
            argumentos = parse_arguments(llamada.arguments, tool.parameters)
        except ArgumentError as exc:
            logger.warning("Argumentos inválidos para la herramienta %s: %s", llamada.name, exc)
            # Los argumentos crudos van al paso persistido (son internos y son
            # justo lo que hace falta para reproducir el fallo), nunca al log.
            paso["raw_arguments"] = llamada.arguments
            return self._cerrar(paso, inicio, STATUS_INVALID_ARGUMENTS, error=str(exc))

        paso["arguments"] = argumentos

        try:
            resultado = await tool.run(argumentos)
        except ToolFailed as exc:
            logger.warning(
                "La herramienta %s no pudo completarse: %s", llamada.name, exc.cause or exc
            )
            return self._cerrar(paso, inicio, STATUS_ERROR, error=str(exc), cause=exc.cause)
        except Exception as exc:  # noqa: BLE001 - una tool no puede tumbar el chat
            # Bug nuestro o error no previsto de una librería. Se degrada igual
            # que un ``ToolFailed`` —el usuario no tiene por qué pagar por
            # esto— pero con traza, porque hay algo que arreglar.
            logger.exception("Fallo inesperado ejecutando la herramienta %s.", llamada.name)
            return self._cerrar(
                paso,
                inicio,
                STATUS_ERROR,
                error="La herramienta falló de forma inesperada. Responde sin ese dato.",
                cause=f"{type(exc).__name__}: {exc}",
            )

        return self._cerrar(paso, inicio, STATUS_OK, result=dict(resultado))

    def _cerrar(
        self,
        paso: dict[str, Any],
        inicio: float,
        status: str,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
        cause: str | None = None,
    ) -> str:
        """Cierra el paso, lo instrumenta y serializa lo que se le manda al modelo.

        Un solo sitio para las tres cosas: así ningún camino de fallo puede
        olvidarse de dejar rastro, que es justo lo que pasa cuando cada
        ``except`` construye su propio diccionario.
        """
        duracion = (time.perf_counter() - inicio) * 1000.0
        paso["status"] = status
        paso["duration_ms"] = round(duracion, 1)
        if result is not None:
            paso["result"] = dict(result)
        if error is not None:
            paso["error"] = error
        if cause is not None:
            # Diagnóstico técnico: al log y al paso persistido, jamás al modelo
            # ni al cliente.
            paso["cause"] = cause
        self._steps.append(paso)

        tool_logger.log(
            logging.INFO if status == STATUS_OK else logging.WARNING,
            "herramienta %s → %s (%.1f ms)",
            paso["tool"],
            status,
            duracion,
            extra={
                "tool_name": paso["tool"],
                "tool_status": status,
                "tool_duration_ms": round(duracion, 1),
                "tool_iteration": paso["iteration"],
            },
        )

        cuerpo = {"error": error} if result is None else dict(result)
        # ``ensure_ascii=False``: el resultado va al contexto del modelo y un
        # acento escapado cuesta seis tokens donde cabía uno.
        return json.dumps(cuerpo, ensure_ascii=False, default=str)
