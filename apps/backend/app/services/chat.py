"""Un turno de conversación: a quién pertenece, qué se guarda y en qué orden.

Es la mitad del chat que NO sabe de HTTP ni de SSE (esa vive en
``app/api/v1/chat.py``). Aquí solo hay conversaciones, mensajes y el contexto
que se le manda al modelo — mismo reparto que ``services/auth.py``, que habla
con Supabase sin saber qué status va a salir por la API.

## La regla de persistencia de esta HU, en una frase

**El mensaje del usuario se guarda siempre que el turno arranque; el del
asistente SOLO si el stream terminó completo.**

De ahí salen las tres respuestas a los casos difíciles del streaming, y no al
revés (ver el porqué en ``app/api/v1/chat.py``): un fallo antes de empezar no
deja rastro, y un fallo a mitad —o un cliente que se va— deja la pregunta sin
respuesta. Lo que NUNCA queda en la tabla es una respuesta a medias, porque
esa fila volvería a entrar en el contexto del modelo en el turno siguiente
(HU-2.5) como si Rover hubiera dicho eso y se hubiera callado.
"""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, MessageRole, select_live_conversations
from app.services.llm import Message as LLMMessage
from app.services.llm import Role as LLMRole

logger = logging.getLogger(__name__)

#: Largo máximo del título derivado. La columna admite 120; se corta muy por
#: debajo porque esto es una ETIQUETA para una lista lateral, no un resumen.
MAX_TITULO_CHARS = 60

#: Mapa de roles PERSISTIDOS a roles del contexto del modelo. Existe como
#: función y no como ``LLMRole(message.role.value)`` para que el día que
#: ``MessageRole`` gane un valor (``tool``, HU-2.6) el compilador obligue a
#: decidir qué hacer con él en vez de traducirlo por casualidad.
_ROL_AL_MODELO: dict[MessageRole, LLMRole] = {
    MessageRole.USER: LLMRole.USER,
    MessageRole.ASSISTANT: LLMRole.ASSISTANT,
}


def derive_title(mensaje: str) -> str:
    """Título de una conversación nueva a partir de su primer mensaje.

    Derivación SIMPLE y determinista, como fija la HU-2.3: colapsa espacios y
    corta. Generarlo con el modelo costaría una llamada extra en el momento
    más sensible del producto —justo antes de la primera respuesta, que es la
    que el usuario está esperando— para producir una etiqueta que casi nadie
    lee. Queda para cuando haya una razón mejor que "se puede".
    """
    limpio = " ".join(mensaje.split())
    if len(limpio) <= MAX_TITULO_CHARS:
        return limpio
    return limpio[: MAX_TITULO_CHARS - 1].rstrip() + "…"


async def load_conversation(
    db: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    """La conversación VIVA de ese usuario, o ``None``.

    ``None`` cubre tres situaciones a propósito —no existe, es de otra
    persona, está en la papelera— porque las tres deben responder lo mismo
    hacia fuera (ver el 404 del endpoint). Que colapsen aquí, en la consulta,
    y no en un ``if`` del endpoint es lo que impide que un refactor futuro las
    separe sin querer.

    Se construye sobre ``select_live_conversations`` para heredar el filtro
    ``deleted_at IS NULL`` en vez de repetirlo (HU-2.3).
    """
    consulta = select_live_conversations(user_id).where(Conversation.id == conversation_id)
    return (await db.execute(consulta)).scalars().first()


async def next_sequence(db: AsyncSession, conversation_id: uuid.UUID) -> int:
    """Siguiente posición libre del hilo (0 si está vacío).

    ``MAX(sequence) + 1`` calculado en la base y no contando filas en Python:
    el conteo se equivocaría en cuanto un mensaje se borrara alguna vez.
    """
    maximo = await db.scalar(
        select(func.max(Message.sequence)).where(Message.conversation_id == conversation_id)
    )
    return 0 if maximo is None else int(maximo) + 1


async def append_message(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
) -> Message:
    """Añade un mensaje al final del hilo y lo commitea.

    Reintenta UNA vez ante ``IntegrityError``: dos peticiones simultáneas de la
    misma conversación (dos pestañas abiertas) pueden calcular el mismo
    ``sequence`` y la ``UNIQUE`` de la HU-2.3 hace fallar a la segunda. Ese es
    justo el diseño —la carrera se ve en el INSERT en vez de reordenar el
    contexto en silencio—, y aquí se resuelve releyendo el máximo, que ya
    incluye la fila del que ganó. Un solo reintento: si vuelve a chocar, el
    problema no es la carrera.
    """
    for intento in range(2):
        mensaje = Message(
            conversation_id=conversation_id,
            role=role,
            sequence=await next_sequence(db, conversation_id),
            content=content,
        )
        db.add(mensaje)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if intento == 1:
                raise
            logger.warning(
                "Colisión de sequence en la conversación %s; se recalcula.", conversation_id
            )
            continue
        return mensaje
    raise AssertionError("inalcanzable")  # pragma: no cover


async def start_turn(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation: Conversation | None,
    mensaje: str,
) -> tuple[Conversation, bool]:
    """Deja el turno arrancado: la conversación existe y la pregunta está guardada.

    Devuelve la conversación y si acaba de crearse (el cliente lo necesita para
    añadirla a su lista sin recargar). El ``user_id`` viene del token y jamás
    del cuerpo: por eso es un parámetro de esta función y no un campo del
    request.
    """
    creada = conversation is None
    if conversation is None:
        # El UUID se genera en Python (HU-2.3), así que el id ya está
        # disponible para el primer evento del SSE sin releer la fila.
        conversation = Conversation(id=uuid.uuid4(), user_id=user_id, title=derive_title(mensaje))
        db.add(conversation)
        await db.flush()

    await append_message(
        db, conversation_id=conversation.id, role=MessageRole.USER, content=mensaje
    )
    return conversation, creada


def build_context(*, mensaje: str, historial: Sequence[Message] = ()) -> list[LLMMessage]:
    """Arma el contexto que se le manda al modelo, en el orden del prefijo estable.

    El system prompt NO va aquí: es un parámetro aparte de la capa de LLM
    (HU-2.1) que ella antepone siempre en la misma posición. Lo que se devuelve
    es lo que va DESPUÉS de él:

        system (aparte) → [definiciones de tools, HU-2.6] → historial → mensaje nuevo

    **Punto de extensión de la HU-2.5.** Hoy ``historial`` llega vacío desde el
    endpoint y el contexto es un único mensaje: esta HU es "conversación de un
    turno". La memoria multi-turno consiste en leer los mensajes con
    ``select_conversation_messages``, recortarlos por PRESUPUESTO DE TOKENS —no
    por número de turnos— y pasarlos por aquí. El parámetro ya existe y ya se
    ordena bien para que ese cambio sea una llamada distinta desde el endpoint
    y no una reescritura de la firma.
    """
    contexto = [
        LLMMessage(role=_ROL_AL_MODELO[m.role], content=m.content)
        for m in historial
        # Un turno del asistente sin texto (posible desde la HU-2.6, cuando el
        # turno fue solo herramientas) no aporta nada al contexto y algunos
        # proveedores rechazan un ``content`` vacío.
        if m.content
    ]
    contexto.append(LLMMessage(role=LLMRole.USER, content=mensaje))
    return contexto
