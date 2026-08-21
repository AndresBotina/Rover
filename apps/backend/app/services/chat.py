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
(y ese turno siguiente ya existe: ver abajo) como si Rover hubiera dicho eso y
se hubiera callado.

## La memoria: qué se le reenvía al modelo (HU-2.5)

Rover no recuerda porque el modelo recuerde —no recuerda nada entre llamadas—,
sino porque en cada turno se le vuelve a contar la conversación. Eso se paga
en tokens **en cada turno**, así que la pregunta no es *"¿cuánto cabe?"* sino
*"¿cuánto conviene?"*:

- **Recortar por TOKENS y no por número de turnos.** Diez turnos pueden ser
  300 tokens o 30.000 según lo que se haya escrito; un tope por turnos deja el
  costo —y el riesgo de reventar el contexto— a merced de lo larga que sea una
  respuesta. El presupuesto está en ``ROVER_CHAT_CONTEXT_TOKEN_BUDGET``.
- **No es solo costo, es calidad.** Con entradas largas los modelos atienden
  peor a lo que queda por el medio (*lost in the middle*), así que mandar todo
  el historial "por si acaso" empeora las respuestas además de encarecerlas.
- **Stable-prefix-first.** El system prompt va primero, aparte e invariable
  (lo antepone la capa de LLM), y lo variable va detrás. Es lo que hace que el
  caché de DeepSeek muerda: en la HU-2.2 se midió 98 % de la entrada servida
  de caché con el prefijo estable delante.

Ver ``build_context`` y ``trim_to_budget`` para el detalle del recorte, y
``estimate_tokens`` para cómo se cuenta y con qué margen de error.
"""

import logging
import uuid
from collections.abc import Sequence
from math import ceil

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Conversation,
    Message,
    MessageRole,
    select_conversation_messages,
    select_live_conversations,
)
from app.services.llm import Message as LLMMessage
from app.services.llm import Role as LLMRole

logger = logging.getLogger(__name__)

#: Envoltorio que el formato del proveedor le pone a CADA mensaje (rol y
#: delimitadores). Se paga aunque el texto sea de una palabra, así que se suma
#: por mensaje al estimar; sin él, una conversación de muchos turnos cortos se
#: subestimaría justo donde más envoltorios hay.
_TOKENS_POR_MENSAJE = 4

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

    **Toca la conversación** (``updated_at``) en la MISMA transacción. Es la
    deuda que dejaron anotada la HU-2.3 y la HU-2.4: el ``onupdate`` de la
    columna salta cuando se actualiza *esa* fila, y añadir un mensaje no la
    toca, así que sin este UPDATE la lista de conversaciones —que ordena por
    ``updated_at desc``— acabaría ordenando por fecha de CREACIÓN y una
    conversación vieja que se retoma no subiría. El síntoma habría sido una
    lista mal ordenada, no un error, que es justo lo que hace que valga la pena
    resolverlo en el sitio y no confiarlo a la memoria de cada llamador.

    El UPDATE es explícito y no una asignación por el ORM: ``func.now()``
    deja el reloj de la BASE como única fuente de la hora, igual que el
    ``server_default`` de la columna. Mezclar el reloj del proceso con el de la
    base en la misma columna permitiría que un ``updated_at`` quedara ANTES de
    su ``created_at`` con solo un poco de deriva entre relojes.
    """
    for intento in range(2):
        mensaje = Message(
            conversation_id=conversation_id,
            role=role,
            sequence=await next_sequence(db, conversation_id),
            content=content,
        )
        db.add(mensaje)
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
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


def estimate_tokens(texto: str) -> int:
    """Estimación PESIMISTA de cuántos tokens ocupa un texto.

    **Es una aproximación por caracteres, no un tokenizador**, y la decisión es
    deliberada:

    - DeepSeek **no publica un tokenizador instalable** para su V4. El de
      OpenAI (``tiktoken``) es otro BPE: daría una cifra precisa… de un modelo
      distinto, que es precisión falsa. Y traerlo añade una dependencia que
      **descarga un fichero de modelo en el primer uso** — una llamada a la red
      en el arranque, en un CI que corre sin secretos y en un plan free que se
      duerme.
    - Lo que se necesita aquí no es contar exacto: es **no pasarse**. Una
      estimación que se queda corta en la cuenta manda de más y el proveedor
      responde `400`; una que se pasa manda de menos y solo se pierde algo de
      memoria vieja. Los dos errores no cuestan lo mismo, así que el estimador
      se inclina a propósito hacia el barato.

    Por eso ``ROVER_CHAT_CONTEXT_CHARS_PER_TOKEN`` vale **3,0**: el español
    real ronda 3,5-4,0 caracteres por token, así que esto **sobreestima
    alrededor de un 20 %** y recorta antes de tiempo. El margen es conocido y
    **medible**, no una corazonada: la instrumentación de la HU-2.1 ya registra
    el ``llm_input_tokens`` REAL de cada llamada, así que comparar esa serie
    con lo estimado dice si el 3,0 sobra o falta — y ajustarlo es cambiar
    entorno, no código.

    Se suma ``_TOKENS_POR_MENSAJE`` por mensaje: en el formato del proveedor
    cada turno viaja envuelto (rol y delimitadores), y ese envoltorio se paga
    aunque el texto sea de una palabra. Sin ese sumando, una conversación de
    muchos mensajes cortos se subestimaría justo donde más mensajes hay.
    """
    if not texto:
        return _TOKENS_POR_MENSAJE
    return _TOKENS_POR_MENSAJE + ceil(len(texto) / settings.chat_context_chars_per_token)


def trim_to_budget(historial: Sequence[Message], *, budget: int | None = None) -> list[Message]:
    """Recorta el historial a los mensajes MÁS RECIENTES que quepan en el presupuesto.

    Se recorre de atrás hacia adelante porque lo que hay que conservar cuando
    no cabe todo es **lo último**: el contexto que da sentido a la pregunta que
    se acaba de hacer. Lo viejo es lo prescindible.

    ## El borde: no se empieza por una respuesta huérfana

    Si el corte cae entre una pregunta y su respuesta, el historial empezaría
    por un mensaje ``assistant`` **sin la pregunta que lo provocó**. Eso se
    descarta, y no por estética:

    - El modelo lo lee como si Rover hubiera dicho eso **por su cuenta**, sin
      que nadie preguntara. Y lo que suele haber ahí es media respuesta a algo
      invisible, que invita a "continuarla" en vez de atender lo que se está
      preguntando ahora.
    - El formato de chat del proveedor asume turnos que alternan; abrir con
      ``assistant`` es una forma rara que no aporta nada.

    El costo es tirar un mensaje que sí cabía. Es barato, y el borde deja de
    existir en vez de quedar dependiendo de dónde caiga el corte.

    Si al quitar los huérfanos no queda nada, se devuelve vacío: el turno se
    comporta como el primero de la conversación, que es lo honesto — con ese
    presupuesto no hay memoria que reenviar.
    """
    presupuesto = settings.chat_context_token_budget if budget is None else budget

    conservados: list[Message] = []
    gastado = 0
    for mensaje in reversed(historial):
        coste = estimate_tokens(mensaje.content)
        if gastado + coste > presupuesto:
            # Se para en el primero que no cabe y NO se sigue buscando alguno
            # más viejo que sí quepa: saltarse un turno del medio dejaría una
            # conversación con un agujero, que el modelo leería como una
            # secuencia continua y le haría atribuir a una pregunta la
            # respuesta de otra.
            break
        conservados.append(mensaje)
        gastado += coste

    conservados.reverse()

    # Quita del principio lo que no sea una pregunta del usuario.
    primero_util = 0
    while (
        primero_util < len(conservados) and conservados[primero_util].role is not MessageRole.USER
    ):
        primero_util += 1
    return conservados[primero_util:]


async def load_history(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    """Los mensajes ya guardados de la conversación, en su orden estable.

    Usa ``select_conversation_messages`` (HU-2.3) para heredar el ``ORDER BY
    sequence`` en vez de repetirlo — el orden es parte del contrato de la
    tabla, no algo que cada llamador deba recordar.
    """
    return list((await db.execute(select_conversation_messages(conversation_id))).scalars().all())


def build_context(*, mensaje: str, historial: Sequence[Message] = ()) -> list[LLMMessage]:
    """Arma el contexto que se le manda al modelo, en el orden del prefijo estable.

    El system prompt NO va aquí: es un parámetro aparte de la capa de LLM
    (HU-2.1) que ella antepone siempre en la misma posición. Lo que se devuelve
    es lo que va DESPUÉS de él:

        system (aparte) → [definiciones de tools, HU-2.6] → historial → mensaje nuevo

    El ``historial`` que entra ya viene recortado por ``trim_to_budget``: esta
    función traduce, no decide. Separarlas deja el recorte —que es la parte con
    reglas— probable a solas, sin base de datos ni endpoint de por medio.

    ## Los ``tool_steps`` NO se reenvían, y no es un pendiente

    De cada mensaje viaja **solo ``content``**, el texto conversacional. Los
    pasos intermedios de tool-calling (HU-2.6) se guardan —son oro para
    depurar— pero **no vuelven al contexto**, por tres razones que no cambian
    cuando existan:

    1. **Están caducados.** El JSON crudo de una API del clima es un dato de
       *aquel* momento. Reenviarlo tres turnos después le enseña al modelo como
       vigente algo que ya no lo es; peor que no tenerlo.
    2. **Cuestan mucho y aportan poco.** Una respuesta de API puede ocupar más
       tokens que toda la conversación, para decir algo que el turno del
       asistente ya resumió en una frase.
    3. **La conclusión ya está en ``content``.** Lo que el modelo necesita
       recordar de un turno con herramientas es lo que Rover *concluyó*, no
       cómo lo averiguó.

    Lo que sí necesita el formato de cable de la tool (``role="tool"``) es el
    **loop del turno en curso** de la HU-2.6, que lo arma en memoria y lo tira
    al terminar. Por eso esta función no cambia con aquella HU. Si algún día
    conviene que quede rastro de una herramienta en el historial, la extensión
    es una **nota corta sintética** ("consultó el clima de Bogotá"), nunca el
    JSON.
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
