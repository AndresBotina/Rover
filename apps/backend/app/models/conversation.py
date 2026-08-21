"""Modelo de conversaciones y mensajes: la memoria del agente (HU-2.3).

Dos tablas, no una: ``conversations`` es el hilo (a quién pertenece, cómo se
llama, si sigue viva) y ``messages`` son los turnos. Aquí solo vive el modelo
de datos; el endpoint de chat que lo llena es la HU-2.4 y el tool-calling que
llena ``tool_steps`` es la HU-2.6.

## Lo interno y lo que ve el cliente

La decisión de la épica es que los pasos intermedios del tool-calling (qué
herramienta se llamó, con qué argumentos, qué devolvió) **se guardan** —son oro
para depurar y para el router futuro— pero **no se le exponen al cliente**, que
solo recibe texto conversacional. Esa frontera está en la forma de la tabla,
no en la disciplina de quien escriba el endpoint: ``content`` es lo público y
``tool_steps`` es lo interno, en columnas distintas de la MISMA fila. Un
serializador que exponga ``content`` no puede filtrar los pasos por descuido.

## Por qué el rol NO distingue los pasos de herramienta

La API OpenAI-compatible representa el ida y vuelta de una tool como mensajes
propios con ``role="tool"``. Eso es un **formato de cable**, no un modelo de
almacenamiento, y copiarlo aquí tendría un costo concreto: cada lectura de la
conversación —la que arma el contexto (HU-2.5) y la que responde al cliente
(HU-2.4)— tendría que acordarse de filtrar por rol, y el día que una se
olvidara, el usuario vería el JSON crudo de una API del clima. Guardando los
pasos DENTRO del mensaje del asistente que los usó, la fila que se lee ya es
la respuesta y no hay nada que filtrar.

Además el ciclo de vida coincide: los pasos existen *para producir* esa
respuesta, se escriben con ella en el mismo INSERT y desaparecen con ella.
Como filas sueltas podrían quedar huérfanas si la petición muere a mitad del
loop.

Por eso ``MessageRole`` solo tiene ``user`` y ``assistant``, y el CHECK de la
base lo hace cumplir. Reconstruir el formato de cable a partir de
``tool_steps`` es trabajo de la HU-2.6; si algún día conviene guardarlos como
filas, añadir un valor al CHECK es una migración normal — exactamente la razón
por la que aquí no se usa el ENUM nativo de Postgres.

``system`` tampoco se guarda: la personalidad de Rover es un archivo
versionado (HU-2.2) que se antepone en cada llamada. Persistirla por
conversación la duplicaría miles de veces y abriría la puerta a que dos
conversaciones acabaran hablando con personalidades distintas.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Select,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MessageRole(enum.StrEnum):
    """Quién habla en un turno PERSISTIDO de la conversación.

    Es un tipo de almacenamiento, no el del cable: ``app.services.llm.base``
    tiene su propio ``Role``, con ``system`` y ``tool``, que responde a otra
    pregunta (qué se le puede mandar al modelo) y que aquí no se guarda nunca.
    Los valores coinciden a propósito para que la traducción sea directa, y un
    test vigila que no se separen.
    """

    USER = "user"
    ASSISTANT = "assistant"


# VARCHAR + CHECK en vez del ENUM nativo, igual que ``Plan`` en user.py: añadir
# un rol es reemplazar la constraint en una migración normal (el ENUM nativo
# exige ALTER TYPE y no deja quitar valores) y el CHECK funciona igual en
# SQLite (tests). values_callable guarda los VALORES ("user"), no los nombres.
_MessageRoleEnum = Enum(
    MessageRole,
    name="message_role",
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
    values_callable=lambda e: [miembro.value for miembro in e],
)

# En Postgres: JSONB (indexable, operadores nativos). En SQLite (tests): el
# JSON genérico. La migración usa JSONB a secas porque solo corre en Postgres.
_ToolStepsJSON = JSONB().with_variant(JSON(), "sqlite")


class Conversation(Base):
    """Un hilo de chat de un usuario.

    A diferencia de ``UserProfile``, el ``id`` se genera AQUÍ: no es la copia
    de un id que Supabase ya asignó, es una entidad nuestra.
    """

    __tablename__ = "conversations"

    # UUID generado en Python y no con ``gen_random_uuid()`` del servidor: el
    # endpoint de la HU-2.4 abre un stream SSE y necesita el id ANTES de que el
    # INSERT vuelva, para poder anunciarlo en el primer evento; del lado de la
    # base habría que releerlo. Como efecto secundario, el mismo camino de
    # código sirve en SQLite (tests).
    #
    # Es un UUIDv4 (aleatorio): esparce los INSERT por el índice de la clave
    # primaria en vez de concentrarlos al final. Se asume a sabiendas — el
    # índice que de verdad se recorre en caliente es el de
    # (conversation_id, sequence) de los mensajes, no este.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # El dueño. Sale SIEMPRE del id del token (HU-1.6), nunca del cuerpo de la
    # petición: si viniera del cliente, cambiar un UUID en el JSON leería las
    # conversaciones de otra persona.
    #
    # CON ForeignKey, al revés que ``UserProfile.id`` → ``auth.users``. La
    # diferencia no es de gusto: ``auth.users`` es un esquema ajeno, gestionado
    # por el tooling de Supabase y ausente en SQLite; ``user_profiles`` es una
    # tabla NUESTRA, creada por estas mismas migraciones. Aquí la FK no acopla
    # nada que no controlemos y a cambio hace imposible una conversación
    # huérfana.
    #
    # Y es segura pese a que el perfil se materializa de forma perezosa:
    # ``get_current_user`` (api/deps.py) crea el perfil y hace COMMIT antes de
    # que corra el cuerpo de cualquier endpoint protegido, así que cuando la
    # HU-2.4 inserte una conversación la fila del perfil ya existe.
    #
    # ON DELETE CASCADE: borrar la cuenta borra sus conversaciones. Es una
    # regla de retención (y de derecho al olvido) que conviene tener en la
    # base, no en la memoria de quien escriba el borrado de cuenta.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )

    # Etiqueta corta derivada del inicio del primer mensaje (HU-2.4). Cadena
    # vacía por defecto, NUNCA NULL: mismo criterio que ``preferences`` en
    # user.py — con NULL habría dos formas de decir "sin título" y todo lector
    # tendría que tratar las dos. Generarlo con el modelo es futuro.
    title: Mapped[str] = mapped_column(String(120), default="", server_default=text("''"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # OJO: ``onupdate`` salta cuando se actualiza ESTA fila. Añadir un mensaje
    # no la toca, así que quien quiera ordenar por "actividad reciente"
    # (HU-2.5) tendrá que tocar la conversación al escribir el mensaje. Se deja
    # dicho aquí porque el síntoma sería una lista mal ordenada, no un error.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # SOFT-DELETE: NULL = viva, con fecha = borrada por el usuario.
    #
    # Timestamp y no un booleano ``is_deleted`` porque cuesta lo mismo y
    # responde una pregunta más: CUÁNDO. Eso es justo lo que necesitan el
    # purgado por retención ("borra de verdad lo que lleve 30 días en la
    # papelera") y una duda de soporte ("perdí la conversación de ayer"). El
    # booleano no se puede convertir después en timestamp sin inventarse las
    # fechas; el timestamp sí se proyecta a booleano cuando haga falta.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def is_deleted(self) -> bool:
        """Si la conversación está en la papelera (soft-delete)."""
        return self.deleted_at is not None


class Message(Base):
    """Un turno de la conversación: lo que escribió el usuario o respondió Rover."""

    __tablename__ = "messages"

    __table_args__ = (
        # El orden es una propiedad de la conversación, no del mensaje: dos
        # mensajes en la misma posición son un bug. Con la UNIQUE, ese bug
        # falla en el INSERT (ruidoso y en el sitio) en vez de reordenar el
        # contexto en silencio la próxima vez que se lea.
        #
        # Este índice también SIRVE la consulta "los mensajes de esta
        # conversación, en orden": ``conversation_id`` es su columna
        # principal. Por eso la columna no lleva además ``index=True`` — sería
        # un segundo índice con el mismo prefijo, pagando escrituras en el
        # camino más caliente del producto (un mensaje por turno de cada chat)
        # para no servir ninguna consulta que este no sirva ya.
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        # Un ``MAX(sequence) + 1`` mal hecho sobre una conversación vacía es la
        # forma normal de acabar con un negativo aquí.
        CheckConstraint("sequence >= 0", name="ck_messages_sequence_no_negativo"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # ON DELETE CASCADE: el purgado de una conversación se lleva sus mensajes
    # sin que nadie tenga que acordarse del orden. El borrado normal es SOFT
    # (``deleted_at``) y no llega hasta aquí.
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )

    role: Mapped[MessageRole] = mapped_column(_MessageRoleEnum)

    # Posición dentro de la conversación, empezando en 0. Es un entero
    # explícito y NO se ordena por ``created_at``, que es lo que parecería
    # suficiente:
    #
    #   - ``now()`` en Postgres es la hora de INICIO DE LA TRANSACCIÓN. El
    #     mensaje del usuario y la respuesta del asistente se escriben en la
    #     misma transacción, así que reciben el MISMO instante y su orden queda
    #     indefinido. El loop de tools (HU-2.6) empeora el empate: varias filas
    #     de una vez.
    #   - Un empate de timestamps no tiene desempate posible aquí: el id es un
    #     UUID aleatorio, no algo que crezca.
    #
    # ``created_at`` se conserva, pero para responder "cuándo", no "en qué
    # orden". Quien inserte calcula ``MAX(sequence) + 1`` dentro de la
    # transacción; si dos peticiones simultáneas de la misma conversación
    # compiten, la UNIQUE de arriba convierte la carrera en un IntegrityError
    # reintentable (mismo patrón que el alta de perfil en api/deps.py).
    sequence: Mapped[int]

    # PÚBLICO: el texto conversacional, lo único que llega al cliente. Sin
    # límite de longitud a propósito (``Text``, no ``VARCHAR(n)``): un
    # itinerario largo es una respuesta legítima, y acotar lo que escribe el
    # usuario es cosa del borde de la API (HU-2.4), no del tipo de la columna.
    # Vacío por defecto: un mensaje del asistente puede quedarse sin texto si
    # el turno fue solo herramientas (HU-2.6).
    content: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))

    # INTERNO — NO SE EXPONE AL CLIENTE. Pasos intermedios del tool-calling que
    # produjeron este mensaje: qué herramienta, con qué argumentos, qué
    # devolvió. HOY NADIE LO LLENA (las tools llegan en la HU-2.6); existe para
    # que la tabla nazca con la forma correcta y no haya que migrar datos
    # después.
    #
    # Es una LISTA y no un objeto porque lo que se guarda es una SECUENCIA
    # ordenada de pasos (llamada 1 → resultado 1 → llamada 2 → …); envolverla
    # en un dict obligaría a inventar una clave que no significa nada. Lista
    # vacía por defecto, nunca NULL, por el mismo motivo que ``title``: una
    # sola forma de decir "aquí no hubo herramientas".
    tool_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        _ToolStepsJSON, default=list, server_default=text("'[]'")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def select_live_conversations(user_id: uuid.UUID) -> Select[tuple[Conversation]]:
    """Las conversaciones VIVAS de un usuario, de la más reciente a la más vieja.

    Existe para que ``deleted_at IS NULL`` se escriba UNA vez. Repartida por
    los endpoints de la HU-2.4 y la HU-2.5, el día que a una consulta se le
    olvide, el usuario ve reaparecer una conversación que borró — y nada falla.
    """
    return (
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
        # El ``id`` desempata, y no es cosmético: ``updated_at`` NO es único
        # (dos conversaciones tocadas en el mismo instante empatan), y un orden
        # indefinido hace que la lista se baraje sola entre dos refrescos. Con
        # el desempate, además, ``updated_at`` sirve de cursor para paginar por
        # keyset el día que haga falta — sobre una clave no única, esa
        # paginación se saltaría filas o las repetiría en el borde de página.
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )


def select_conversation_messages(conversation_id: uuid.UUID) -> Select[tuple[Message]]:
    """Los mensajes de una conversación, en su orden estable (``sequence``).

    Mismo motivo que arriba: el orden es parte del contrato de la tabla (ver
    ``Message.sequence``), no algo que cada llamador deba recordar.
    """
    return (
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sequence)
    )
