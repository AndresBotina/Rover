"""`POST /v1/chat` — conversar con Rover en streaming (HU-2.4).

El primer punto por el que un usuario habla con Rover de verdad: manda un
mensaje, ve la respuesta aparecer trozo a trozo y la conversación queda
guardada. Sin herramientas todavía (HU-2.6) y con memoria de UN turno (la
ventana multi-turno es la HU-2.5, con el punto de extensión ya marcado en
``services/chat.build_context``).


## Los tres fallos de un endpoint que hace streaming

Un endpoint normal tiene un momento para fallar. Este tiene tres, y cada uno
admite una respuesta distinta porque cambia lo que ya se le mandó al cliente:

1. **ANTES de abrir el stream** — el proveedor rechaza la petición (sin saldo,
   key inválida, contexto demasiado largo). Todavía no salió ninguna cabecera,
   así que se responde con un **status HTTP normal** y el cuerpo de error de la
   HU-1.8. Para llegar a esto hay que saberlo antes de empezar a responder, y
   por eso el endpoint **pide el primer trozo al modelo ANTES de devolver la
   respuesta** (ver ``_primer_trozo``).

2. **A MITAD del stream** — ya salió un `200 OK` y puede que texto. Cambiar el
   status es imposible, así que el error va **dentro del SSE**, como un evento
   con el mismo cuerpo de la HU-1.8 (mismo catálogo de ``code``), y el stream
   se cierra limpio. La causa real —status y mensaje del proveedor— va al log
   con el ``request_id`` de la petición (HU-1.12), nunca al cliente.

3. **El cliente se va** (cierra la pestaña). No hay a quién responder; lo único
   que importa es **soltar los recursos**: el generador del proveedor se cierra
   con ``aclosing`` para que la conexión HTTP no quede colgando. La
   instrumentación de la HU-2.1 ya lo registra aparte, con
   ``llm_outcome=cancelled``: no fue un fallo, pero los tokens se gastaron.


## Qué se persiste en cada uno (y por qué)

La regla es una sola, y de ella salen los tres casos:
**el mensaje del usuario se guarda al arrancar el turno; el del asistente solo
si el stream terminó completo.**

- *Antes del stream* → **no se escribe nada**. El turno se persiste DESPUÉS del
  primer trozo, así que un proveedor caído deja la base exactamente como
  estaba y reintentar es limpio: sin conversaciones vacías ni preguntas
  duplicadas.
- *A mitad* y *cliente que se va* → queda la pregunta, **se descarta la
  respuesta parcial**. Es la decisión menos obvia de esta HU y no se toma por
  simplicidad: esa fila volvería a entrar en el contexto del modelo en el turno
  siguiente (HU-2.5), y el modelo la leería como *"esto fue lo que Rover
  respondió"* — una frase cortada a mitad, para siempre, contaminando cada
  turno posterior de esa conversación. Guardarla para "no perder los tokens
  gastados" confunde dos cosas distintas: el consumo ya quedó contabilizado en
  la línea de instrumentación de la HU-2.1, que es donde se factura (HU-2.8);
  la tabla de mensajes es la MEMORIA, no el libro de cuentas. El precio
  asumido, dicho claro: quien se va tras leer el 90 % de una respuesta larga la
  pierde.

El efecto es un invariante que se explica en una línea y en el que puede
confiar cualquiera que lea la tabla: **toda fila ``assistant`` es una respuesta
completa.** Si el aborto descartara y el error a mitad guardara —o al revés—,
el estado de una conversación tras un fallo dependería de CUÁL fallo, y nadie
podría razonar sobre el historial sin conocer la historia de cada turno.
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AUTH_RESPONSES, CurrentUser, enforce_user_rate_limit, get_current_user
from app.api.sse import SSE_HEADERS, SSE_MEDIA_TYPE, sse_error_event, sse_event
from app.core.database import get_db
from app.core.errors import ApiError, ErrorCode, error_doc
from app.models import MessageRole
from app.services import chat
from app.services.llm import (
    DEFAULT_SYSTEM_PROMPT,
    CompletionChunk,
    LLMBadRequest,
    LLMError,
    LLMRateLimited,
    get_llm_provider,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    # Igual que ``users``: la cuota por usuario (HU-1.7) se declara a nivel de
    # ROUTER. Aquí importa el doble —una petición de chat cuesta tokens de
    # verdad— y así el endpoint no puede nacer sin límite por olvido.
    dependencies=[Depends(enforce_user_rate_limit)],
)

#: Tope del mensaje entrante. Generoso a propósito (unos 2.000 tokens): pegar
#: un itinerario para que Rover lo comente es un uso legítimo. Lo que corta es
#: el disparate —un fichero pegado entero—, que el proveedor rechazaría después
#: con un error mucho peor de explicar.
MAX_MENSAJE_CHARS = 8000

_NO_ENCONTRADA = "No encontramos esa conversación."

#: Traducción de un fallo del LLM al contrato de la API (HU-1.8). Una sola
#: tabla para los DOS caminos —status HTTP antes del stream, evento SSE a
#: mitad—: el cliente ve el mismo ``code`` para la misma causa, y por dónde
#: llegó es un detalle del transporte, no del error.
#:
#: Casi todo cae en 503 y no es pereza: que a Rover se le acabe el saldo, que
#: su key esté revocada o que el proveedor esté caído son problemas NUESTROS.
#: El usuario no puede hacer nada distinto en ninguno de los tres, y decirle
#: cuál es contaría de más sobre la infraestructura (la misma razón por la que
#: el 401 de la HU-1.6 es uniforme).
_MSG_NO_DISPONIBLE = "Rover no está disponible en este momento. Inténtalo de nuevo en un momento."
_MSG_MENSAJE_RECHAZADO = "No pudimos procesar ese mensaje. Prueba a reformularlo o acortarlo."


def _api_error_de(exc: LLMError) -> ApiError:
    """Convierte un error de dominio del LLM en el ``ApiError`` que toca."""
    if isinstance(exc, LLMRateLimited):
        # El límite lo puso el proveedor, no la API — pero para quien llama la
        # acción es idéntica (esperar y reintentar) y el ``code`` describe el
        # dominio, no de dónde salió. Mismo criterio ya aplicado con el 429 de
        # Supabase en la HU-1.3.
        return ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.RATE_LIMITED, _MSG_NO_DISPONIBLE
        )
    if isinstance(exc, LLMBadRequest):
        # Reintentar tal cual volvería a fallar: contexto demasiado largo o
        # filtro de contenido. Es lo único que el usuario sí puede corregir.
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_ERROR,
            _MSG_MENSAJE_RECHAZADO,
        )
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.SERVICE_UNAVAILABLE, _MSG_NO_DISPONIBLE
    )


def _log_fallo_del_llm(exc: LLMError, *, momento: str) -> None:
    """Deja la causa REAL en el log del servidor; al cliente solo va el genérico.

    El diagnóstico del proveedor viaja en atributos aparte de la excepción
    justo para esto (HU-2.1). El ``request_id`` lo cuelga el filtro de la
    HU-1.12 — y sigue disponible dentro del generador del stream, porque el
    middleware de contexto no lo suelta hasta que la respuesta termina de
    enviarse.
    """
    logger.warning(
        "Fallo del LLM %s del stream de chat: %s (status=%s code=%s) %s",
        momento,
        type(exc).__name__,
        exc.provider_status,
        exc.provider_error_code,
        exc.provider_message or "",
        extra={
            "llm_error": type(exc).__name__,
            "llm_provider_status": exc.provider_status,
            "chat_stage": momento,
        },
    )


class ChatRequest(BaseModel):
    """Cuerpo de ``POST /v1/chat``.

    ``extra='forbid'``: mandar ``user_id`` (o cualquier otro campo) responde
    422 en vez de ignorarse en silencio. Importa más que en un PATCH normal —
    el dueño de la conversación sale SIEMPRE del token, y un campo que parezca
    aceptarse invitaría a un cliente a intentarlo.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"message": "¿Qué hago tres días en Medellín?", "conversation_id": None},
                {
                    "message": "¿Y si llueve?",
                    "conversation_id": "0f6c2f9e-1f2a-4c3b-9d5e-8a7b6c5d4e3f",
                },
            ]
        },
    )

    #: Se recortan los espacios ANTES de validar el mínimo: un mensaje de puros
    #: espacios es un mensaje vacío, y llegaría al modelo como una llamada
    #: pagada que no pregunta nada.
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MENSAJE_CHARS),
    ] = Field(description="Lo que el usuario le dice a Rover.")

    #: Ausente o ``null`` = conversación nueva. Que exista NO da acceso: se
    #: comprueba contra el usuario del token antes de tocar nada.
    conversation_id: uuid.UUID | None = Field(
        default=None,
        description="Conversación existente a continuar. Si falta, se crea una nueva.",
    )


async def _primer_trozo(stream: AsyncGenerator[CompletionChunk]) -> CompletionChunk | None:
    """Pide el primer trozo al modelo, aún con la respuesta HTTP sin abrir.

    Es lo que separa el fallo (1) del (2) del docstring del módulo: hasta que
    esto vuelve no se ha enviado ninguna cabecera, así que un rechazo del
    proveedor todavía puede salir como un status HTTP de verdad —con sus
    handlers, su formato de error y sus cabeceras de CORS— en vez de como un
    `200 OK` que se convierte en un error dos bytes después.

    El precio, asumido: el tiempo hasta la PRIMERA cabecera incluye ahora la
    latencia del modelo hasta su primer token. No se pierde nada de cara al
    usuario (esa espera existía igual, solo que después del 200) y se gana que
    "el proveedor está caído" sea un error HTTP normal, que es como los
    clientes ya saben tratarlo.

    Devuelve ``None`` si el modelo no emitió nada: raro, pero no es un fallo.
    """
    return await anext(stream, None)


@router.post(
    "",
    summary="Conversar con Rover (respuesta en streaming SSE)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Stream de eventos SSE. Cada marco es `data: {...}` con un JSON "
                "discriminado por `type`: `start` (trae el `conversation_id`), "
                "`delta` (un trozo de texto: concatenarlos en orden reconstruye "
                "la respuesta), `done` (fin correcto) y `error` (fallo **a mitad** "
                "del stream, con el mismo cuerpo que un error HTTP)."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        404: error_doc(
            "`not_found` — el `conversation_id` no existe, está borrado o es de "
            "otra persona. Los tres casos responden **lo mismo** a propósito: "
            "distinguirlos convertiría el id en un oráculo para averiguar qué "
            "conversaciones existen."
        ),
        422: error_doc(
            "`validation_error` — el cuerpo no cumple el contrato (mensaje "
            "vacío, demasiado largo o un campo de más), o el modelo rechazó el "
            "mensaje antes de empezar a responder."
        ),
        **AUTH_RESPONSES,
    },
)
async def chat_stream(
    payload: ChatRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Manda un mensaje a Rover y recibe la respuesta **en streaming (SSE)**.

    Sin `conversation_id` se crea una conversación nueva (el primer evento del
    stream trae su id, para que el cliente sepa a cuál pertenece lo que está
    leyendo). Con él, se continúa esa conversación **si es del dueño del
    token**.

    El mensaje del usuario queda guardado al arrancar el turno; la respuesta de
    Rover, solo si el stream termina completo.
    """
    conversacion = None
    if payload.conversation_id is not None:
        conversacion = await chat.load_conversation(
            db, user_id=user.id, conversation_id=payload.conversation_id
        )
        if conversacion is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, _NO_ENCONTRADA)

    # La MEMORIA (HU-2.5): se relee lo ya guardado y se recorta a lo que quepa
    # en el presupuesto de tokens. En una conversación nueva esto es una lista
    # vacía y el contexto queda igual que en la HU-2.4.
    historial = chat.trim_to_budget(
        await chat.load_history(db, conversacion.id) if conversacion is not None else []
    )
    contexto = chat.build_context(mensaje=payload.message, historial=historial)

    try:
        provider = get_llm_provider()
        stream = provider.stream(contexto, system_prompt=DEFAULT_SYSTEM_PROMPT)
    except LLMError as exc:  # el proveedor ni siquiera está configurado
        _log_fallo_del_llm(exc, momento="antes")
        raise _api_error_de(exc) from exc

    try:
        primero = await _primer_trozo(stream)
    except LLMError as exc:
        await stream.aclose()
        _log_fallo_del_llm(exc, momento="antes")
        raise _api_error_de(exc) from exc

    # A partir de aquí el modelo ya está respondiendo: recién ahora se escribe.
    try:
        conversacion, creada = await chat.start_turn(
            db, user_id=user.id, conversation=conversacion, mensaje=payload.message
        )
    except BaseException:
        # Incluye la cancelación: si no se llega a devolver la respuesta, nadie
        # más va a cerrar el generador del proveedor.
        await stream.aclose()
        raise

    return StreamingResponse(
        _eventos(
            stream,
            primero=primero,
            conversation_id=conversacion.id,
            creada=creada,
        ),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


async def _eventos(
    stream: AsyncGenerator[CompletionChunk],
    *,
    primero: CompletionChunk | None,
    conversation_id: uuid.UUID,
    creada: bool,
) -> AsyncGenerator[str]:
    """El cuerpo del SSE: ``start`` → ``delta``* → (``done`` | ``error``).

    ``aclosing`` sobre el stream del proveedor es lo que hace correcto el caso
    del cliente que se va: cuando Starlette detecta la desconexión, cancela la
    tarea que consume este generador, la cancelación entra por el ``yield`` y
    el ``async with`` cierra el generador de abajo —y con él la conexión HTTP
    con DeepSeek— en el momento, en vez de dejarla colgando hasta que pase el
    recolector. Es la razón por la que la HU-2.1 tipó ``stream`` como
    ``AsyncGenerator`` y no como ``AsyncIterator``.

    Como la cancelación NO es una ``LLMError``, no la captura nadie aquí: sube,
    el generador se desmonta y el mensaje del asistente no se escribe. Eso es
    lo previsto, no un descuido.
    """
    partes: list[str] = []
    try:
        yield sse_event(
            {"type": "start", "conversation_id": str(conversation_id), "created": creada}
        )
        async with aclosing(stream):
            # El trozo que se pidió antes de abrir la respuesta no se pierde:
            # es el primero que sale por el cable.
            if primero is not None and primero.text:
                partes.append(primero.text)
                yield sse_event({"type": "delta", "text": primero.text})
            async for trozo in stream:
                # El trozo final del proveedor viene sin texto y solo con el
                # consumo: no hay nada que mandarle al cliente.
                if not trozo.text:
                    continue
                partes.append(trozo.text)
                yield sse_event({"type": "delta", "text": trozo.text})
    except LLMError as exc:
        _log_fallo_del_llm(exc, momento="a mitad")
        yield sse_error_event(ErrorCode.SERVICE_UNAVAILABLE, _MSG_NO_DISPONIBLE)
        return

    try:
        sequence = await _persistir_respuesta(conversation_id, "".join(partes))
    except SQLAlchemyError:
        # Ni traza ni mensaje: pueden llevar la URL de la base con credenciales
        # (mismo criterio que ``get_current_user``).
        logger.error("No se pudo guardar la respuesta de la conversación %s.", conversation_id)
        yield sse_error_event(ErrorCode.SERVICE_UNAVAILABLE, _MSG_NO_DISPONIBLE)
        return

    yield sse_event({"type": "done", "sequence": sequence})


async def _persistir_respuesta(conversation_id: uuid.UUID, texto: str) -> int:
    """Guarda el mensaje del asistente en su PROPIA sesión y devuelve su ``sequence``.

    No se reutiliza la sesión que inyectó ``Depends(get_db)`` en el endpoint: el
    cuerpo de un ``StreamingResponse`` se ejecuta DESPUÉS de que la función del
    endpoint devolvió, y de cuándo exactamente cierra FastAPI una dependencia
    con ``yield`` depende de su versión. Depender de eso sería construir el
    camino más caliente del producto sobre un detalle de implementación de
    terceros; abrir una sesión propia cuesta lo mismo y no admite dos lecturas.

    El patrón de iterar ``get_db()`` a mano con ``aclosing`` es el mismo que usa
    ``_resolve_or_create_profile`` (HU-1.6), y por la misma razón: esta función
    sale con ``return`` desde dentro del ``async for``, lo que dejaría el
    generador suspendido en su ``yield`` —con la sesión y su conexión abiertas—
    hasta que pasara el recolector.
    """
    async with aclosing(get_db()) as sesiones:
        async for session in sesiones:
            mensaje = await chat.append_message(
                session,
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=texto,
            )
            return mensaje.sequence
    raise RuntimeError("get_db no entregó una sesión")  # pragma: no cover
