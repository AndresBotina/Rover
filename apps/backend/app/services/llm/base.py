"""Contrato del proveedor de LLM: tipos de dominio, errores e interfaz.

Este módulo es el **único** que el resto del backend necesita conocer para
hablar con un modelo. No importa nada de DeepSeek, ni de OpenAI, ni de httpx:
lo que hay detrás se elige en ``registry.py`` y se implementa en un módulo
aparte (``deepseek.py``). Es la misma jugada que ``RateLimitStore`` en la
HU-1.7 — la interfaz es lo estable, la implementación es lo desechable.


## Por qué tipos propios y no los del proveedor

El endpoint de DeepSeek es OpenAI-compatible, así que sería tentador pasear
sus ``dict`` (``{"role": ..., "content": ...}``, ``choices[0].delta.content``)
por el agente, el endpoint SSE y la persistencia. Eso ataría TODO el backend a
la forma de una API de terceros: el día que el proveedor renombre un campo,
parta ``content`` en bloques o cambie la forma del stream, el cambio se
propagaría hasta el modelo de datos de las conversaciones (HU-2.3).

Con ``Message``, ``Completion`` y ``CompletionChunk`` propios, ese día solo se
toca el traductor de ``deepseek.py``. Es exactamente el mismo criterio por el
que los ``error_code`` de Supabase no salen de ``services/auth.py`` y por el
que el catálogo ``ErrorCode`` es de dominio (HU-1.8).


## El system prompt es un parámetro APARTE, no un mensaje más

``complete``/``stream`` reciben ``system_prompt`` por separado y la
implementación lo antepone SIEMPRE, en la misma posición y sin variaciones.
No es cosmética: el caché automático de DeepSeek acierta sobre el **prefijo
común** de la petición, así que el orden del contexto es
``system prompt → (definiciones de tools, HU-2.6) → historial → mensaje nuevo``.
Si el prompt fuera "un mensaje más" de la lista, bastaría con que un llamador
lo pusiera en otro sitio —o lo interpolara con la fecha de hoy— para invalidar
el caché de todas las peticiones sin que nadie se enterase. Aquí la estructura
lo impide por construcción.


## Seam de selección por CAPACIDAD (no implementado, documentado)

``Capability`` existe para que el día que entre un modelo con visión el agente
no cambie: pedirá ``get_llm_provider(Capability.VISION)`` y el registro
devolverá otra implementación. Hoy solo existe la de texto. Lo que NO está —ni
va a estar en esta épica— es el enrutado por DIFICULTAD (mandar lo difícil a un
modelo caro): ese se difiere hasta que la instrumentación de este mismo módulo
demuestre con datos reales dónde falla el modelo barato (ver
``instrumentation.py`` y docs/backlog.md § Diferido).
"""

from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class Capability(StrEnum):
    """Qué debe saber hacer el modelo que atienda una petición.

    Es el punto de selección del registro (``registry.py``). Hoy solo hay
    implementación de ``TEXT``; ``VISION`` está declarada para que el seam sea
    verificable (existe un valor que HOY falla claro) y no una promesa en un
    comentario.
    """

    TEXT = "text"
    VISION = "vision"


class Role(StrEnum):
    """Quién habla en un mensaje del contexto.

    Coincide en nombre con los roles de la API OpenAI-compatible, pero es un
    tipo NUESTRO: la traducción a lo que espera el proveedor se hace en su
    módulo, y un proveedor con otros nombres solo cambiaría ese mapeo.
    """

    #: Instrucciones del sistema (la personalidad de Rover, HU-2.2).
    SYSTEM = "system"
    #: Lo que escribe la persona.
    USER = "user"
    #: Lo que respondió el modelo en turnos anteriores.
    ASSISTANT = "assistant"
    #: Resultado devuelto por una herramienta (HU-2.6).
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """La DECLARACIÓN de una herramienta, tal y como se le presenta al modelo.

    Es lo único que esta capa sabe de las herramientas: un nombre, para qué
    sirve y qué argumentos admite. **No sabe ejecutarlas** — eso vive en
    ``app/services/tools`` (HU-2.6), que construye estos ``ToolSpec`` a partir
    de sus propias herramientas.

    La dependencia va en ese sentido y no al revés a propósito: si el tipo
    viviera en el paquete de tools, la capa de LLM tendría que importarlo y el
    proveedor pasaría a depender del registro de herramientas para poder
    compilar. Así, ``deepseek.py`` traduce una declaración a la forma de su API
    sin enterarse de que existe una herramienta del clima.

    ``parameters`` es un **JSON Schema** (el objeto ``{"type": "object",
    "properties": {...}, "required": [...]}``). No se inventa un lenguaje
    propio de esquemas porque este es el que entienden todas las APIs de
    function-calling; traducirlo a otra cosa para volver a traducirlo sería la
    misma capa de más que se descartó con el SDK de OpenAI.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """El modelo PIDE ejecutar una herramienta. Petición, no resultado.

    ``arguments`` es la cadena JSON **tal cual la emitió el modelo**, sin
    parsear. Es deliberado: un modelo puede mandar JSON roto o argumentos que
    no cumplen el esquema, y eso es un caso normal —no una excepción rara— del
    tool-calling. Si este tipo exigiera un ``dict``, el parseo tendría que
    ocurrir dentro del proveedor, que es el sitio con menos contexto para
    decidir qué hacer cuando falla; dejándolo crudo, quien decide es el loop
    (que puede devolverle el error al modelo para que se corrija).

    ``id`` lo asigna el proveedor y sirve para correlacionar cada resultado con
    su petición cuando el modelo pide varias herramientas de una vez: el
    mensaje de rol ``tool`` viaja con ese mismo id.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """Un FRAGMENTO de una petición de herramienta que llega por el stream.

    En streaming, una petición de tool no llega entera: llega repartida en
    eventos (primero el ``id`` y el nombre, después los argumentos carácter a
    carácter), y varias peticiones simultáneas se distinguen por ``index``.
    Reconstruirlas es trabajo de ``ToolCallAccumulator``, que está aquí y no en
    el proveedor para que cualquier implementación futura lo herede en vez de
    reimplementar el mismo pegado.
    """

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""


class ToolCallAccumulator:
    """Pega los ``ToolCallDelta`` de un stream hasta formar ``ToolCall`` enteros.

    Mutable y de usar y tirar: uno por vuelta del loop de herramientas. Es la
    única pieza con estado de este módulo, y lo es porque el problema lo tiene:
    el stream entrega trozos y alguien debe acordarse de los anteriores.

    Tolerante con lo que falte —un fragmento sin ``id``, sin nombre o sin
    argumentos es normal— porque el objetivo es reconstruir lo que el modelo
    quiso decir, no validarlo: la validación (¿existe esa herramienta? ¿los
    argumentos son JSON?) es de quien ejecuta.
    """

    def __init__(self) -> None:
        # dict y no lista: el ``index`` es la identidad del fragmento, y los
        # proveedores no garantizan que empiece en 0 ni que llegue en orden.
        self._partes: dict[int, dict[str, str]] = {}

    def add(self, delta: ToolCallDelta) -> None:
        """Incorpora un fragmento."""
        parte = self._partes.setdefault(delta.index, {"id": "", "name": "", "arguments": ""})
        if delta.id:
            parte["id"] = delta.id
        if delta.name:
            parte["name"] = delta.name
        # Los argumentos son lo ÚNICO que se concatena: el resto llega entero
        # en el primer fragmento y se repite (o no) en los siguientes.
        parte["arguments"] += delta.arguments

    def result(self) -> tuple[ToolCall, ...]:
        """Las peticiones completas, en el orden de su ``index``.

        Las que se quedaron sin nombre se descartan: son un fragmento que llegó
        suelto por un stream cortado, y una petición sin nombre no se puede ni
        ejecutar ni reportarle al modelo como fallida.
        """
        return tuple(
            ToolCall(
                # Un ``id`` vacío es raro pero no impide seguir: se sintetiza
                # uno estable con el índice para que el mensaje de resultado
                # tenga con qué correlacionarse.
                id=parte["id"] or f"call_{indice}",
                name=parte["name"],
                arguments=parte["arguments"],
            )
            for indice, parte in sorted(self._partes.items())
            if parte["name"]
        )

    def __bool__(self) -> bool:
        return bool(self._partes)


@dataclass(frozen=True, slots=True)
class Message:
    """Un turno del contexto que se le manda al modelo.

    Inmutable a propósito: el contexto se arma y se manda, no se parchea a
    mitad de camino (un ``Message`` mutado después de calcular el presupuesto
    de tokens de la HU-2.5 sería un bug silencioso).

    Los dos campos de herramientas (HU-2.6) son lo que hace posible el
    multi-turno con el proveedor: el turno del asistente que PIDIÓ herramientas
    viaja con ``tool_calls``, y cada resultado vuelve como un mensaje de rol
    ``tool`` con el ``tool_call_id`` de su petición. Ambos con default, así que
    un ``Message(role=..., content=...)` normal —el 99 % del contexto— se
    escribe igual que antes.

    Estos mensajes viven SOLO en el turno en curso: no se persisten como filas
    (ver ``app/models/conversation.py``) ni se reenvían en turnos siguientes
    (ver ``services/chat.build_context``).
    """

    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    """Consumo de una llamada, en tokens.

    ``cached_input_tokens`` son los tokens de entrada que el proveedor sirvió
    de su caché automático (más baratos). Es la señal de si el prefijo estable
    está funcionando: si se acerca a cero llamada tras llamada, algo está
    invalidando el caché y se está pagando de más.
    """

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0

    @property
    def cache_hit(self) -> bool:
        """Si el proveedor reutilizó parte del prefijo desde su caché."""
        return self.cached_input_tokens > 0

    @property
    def cache_hit_ratio(self) -> float:
        """Fracción de la entrada servida desde caché (0.0–1.0).

        Más útil que el booleano para vigilar la eficacia del prefijo estable:
        distingue "acertó en el 5 % del prompt" de "acertó en el 90 %".
        """
        if self.input_tokens <= 0:
            return 0.0
        return min(self.cached_input_tokens / self.input_tokens, 1.0)


@dataclass(frozen=True, slots=True)
class Completion:
    """Respuesta COMPLETA del modelo (camino sin streaming).

    ``usage`` es opcional porque es información que el proveedor REGALA, no
    algo que el contrato pueda garantizar: un proveedor que no la reporte debe
    poder implementar esta interfaz igual.

    ``tool_calls`` es lo que convierte esto en una respuesta de agente y no de
    chat: el modelo puede contestar con texto, con peticiones de herramienta, o
    —aunque es poco común— con las dos cosas (una frase de preámbulo antes de
    consultar). Por eso son campos independientes y no una unión: "texto O
    tools" obligaría a un ``isinstance`` en cada llamador para descubrir que en
    realidad puede haber ambos.
    """

    text: str
    model: str
    usage: Usage | None = None
    finish_reason: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletionChunk:
    """Un trozo del stream: el DELTA de texto nuevo, no el acumulado.

    Concatenar todos los ``text`` en orden reconstruye la respuesta completa —
    ese es el contrato, y es lo que hará el puente a SSE de la HU-2.4.

    El proveedor emite además un chunk FINAL sin texto (``text == ""``) que
    trae ``usage`` y ``finish_reason``: el consumo solo se conoce cuando la
    generación termina, y hacer esperar a ese dato para emitir el último trozo
    de texto añadiría latencia percibida a cambio de nada.

    ``tool_calls`` son FRAGMENTOS (``ToolCallDelta``), no peticiones completas:
    en streaming los argumentos llegan partidos igual que el texto. Quien
    consuma el stream los va metiendo en un ``ToolCallAccumulator`` y pide el
    resultado cuando el stream termina — antes de eso, una petición a medias no
    se puede ejecutar.
    """

    text: str
    finish_reason: str | None = None
    usage: Usage | None = None
    tool_calls: tuple[ToolCallDelta, ...] = ()


class LLMProvider(Protocol):
    """Lo que Rover necesita de "un modelo". Nada más, y nada del proveedor.

    Se implementa por ESTRUCTURA (``Protocol``, no herencia): una
    implementación no tiene que importar este módulo para cumplirlo, y un doble
    de test es una clase de veinte líneas sin ceremonia. Mismo criterio que
    ``RateLimitStore``.

    Los dos caminos —completo y streaming— son métodos SEPARADOS en vez de un
    flag ``stream: bool``, porque devuelven cosas de tipo distinto (un valor vs.
    un async generator). Un flag obligaría a todo llamador a desambiguar en
    tiempo de ejecución lo que el tipo ya sabe en tiempo de compilación.
    """

    @property
    def model(self) -> str:
        """Identificador del modelo concreto que atiende (para logs y métricas)."""
        ...

    @property
    def capabilities(self) -> frozenset[Capability]:
        """Qué sabe hacer. Lo consulta el registro para enrutar por capacidad."""
        ...

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> Completion:
        """Genera la respuesta completa y la devuelve de una vez.

        ``system_prompt`` va SIEMPRE primero (ver el docstring del módulo); si
        es ``None`` se usa el de ``prompt.py``. ``temperature`` y
        ``max_output_tokens`` a ``None`` significan "los de config".

        ``tools`` son las herramientas que el modelo PUEDE pedir en esta
        llamada (HU-2.6). ``None`` o vacío = ninguna, y entonces esto se
        comporta exactamente como antes de aquella HU. Ofrecerlas no obliga al
        modelo a usarlas: decide él, y lo que decidió llega en
        ``Completion.tool_calls``.

        Levanta las excepciones de ``errors.py``: nunca un error del proveedor.
        """
        ...

    def stream(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncGenerator[CompletionChunk]:
        """Igual que ``complete``, pero emitiendo la respuesta por trozos.

        Se usa como ``async for chunk in provider.stream(...)``. Es requisito
        de esta HU y no un extra: el endpoint SSE de la HU-2.4 se apoya
        directamente aquí, y un proveedor que solo supiera responder completo
        haría imposible el "token a token" que ve el usuario.

        El tipo de retorno es ``AsyncGenerator`` y no el más laxo
        ``AsyncIterator`` para exigir ``aclose()``: quien consuma esto va a
        abandonar el stream a mitad de forma habitual —el usuario cierra la
        pestaña y el endpoint SSE deja de leer—, y sin ``aclose()`` la conexión
        con el proveedor queda colgando hasta que pase el recolector. Con él,
        el consumidor cierra en el momento (``contextlib.aclosing``). No es
        exigir de más: cualquier implementación razonable es una función
        generadora asíncrona, y lo cumple sin escribir una línea extra.

        Los errores del proveedor pueden aparecer ANTES del primer trozo (la
        petición fue rechazada) o A MITAD del stream (se cortó la conexión);
        en ambos casos salen como excepciones de ``errors.py`` desde el
        ``async for``.

        Con ``tools``, un turno puede no traer NADA de texto: si el modelo
        decide llamar a una herramienta, todos los chunks vienen con
        ``text == ""`` y con fragmentos en ``tool_calls``. Quien consuma esto
        debe estar preparado para ese stream "mudo" — es lo normal en la
        primera vuelta del loop de herramientas, no un fallo.
        """
        ...
