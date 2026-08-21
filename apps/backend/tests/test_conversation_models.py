"""Tests del modelo de conversaciones y mensajes (HU-2.3) — SIN base real.

El esquema lo crea la fixture ``bd`` desde ``Base.metadata``, sobre la SQLite
sustituta del resto de la suite. Los tipos exclusivos de Postgres están
resueltos en el modelo: ``tool_steps`` es JSONB con variante JSON
(``with_variant``), los ids usan el ``sa.Uuid`` genérico (UUID nativo en
Postgres, texto en SQLite) y ``role`` es VARCHAR + CHECK, idéntico en ambas.

Lo que aquí NO se puede ejercer: SQLite no aplica las foreign keys si no se
enciende ``PRAGMA foreign_keys``, así que de las FK se verifica la
DECLARACIÓN (que existan y con qué ``ondelete``), no su cumplimiento. Que
Postgres las hace cumplir de verdad —y que el CASCADE se lleva mensajes y
conversaciones al borrar el perfil— se comprobó aplicando esta misma migración
contra un Postgres real, fuera de la suite.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import (
    Conversation,
    Message,
    MessageRole,
    select_conversation_messages,
    select_live_conversations,
)
from app.services.llm.base import Role
from tests.conftest import BaseDeTest

_COLUMNAS_DE_CONVERSACION = {
    "id",
    "user_id",
    "title",
    "created_at",
    "updated_at",
    "deleted_at",
}
_COLUMNAS_DE_MENSAJE = {
    "id",
    "conversation_id",
    "role",
    "sequence",
    "content",
    "tool_steps",
    "created_at",
}


def _tabla(modelo: type[Conversation] | type[Message]) -> Table:
    """La Table del modelo (``__table__`` se tipa como FromClause; se estrecha)."""
    tabla = modelo.__table__
    assert isinstance(tabla, Table)
    return tabla


# --------------------------------------------------------------------------
# Declaración de las tablas
# --------------------------------------------------------------------------


def test_declaracion_de_la_tabla_de_conversaciones() -> None:
    """Columnas, tipos, id propio y el único NULL con significado."""
    tabla = _tabla(Conversation)

    assert tabla.name == "conversations"
    assert {columna.name for columna in tabla.columns} == _COLUMNAS_DE_CONVERSACION

    # El id se genera AQUÍ (a diferencia del de user_profiles, que viene de
    # Supabase): hay default propio y es un UUID.
    assert [columna.name for columna in tabla.primary_key.columns] == ["id"]
    assert isinstance(tabla.c.id.type, Uuid)
    assert tabla.c.id.default is not None

    assert isinstance(tabla.c.title.type, String)
    assert tabla.c.title.server_default is not None  # '' , nunca NULL

    # deleted_at es la ÚNICA nullable, y lo es porque NULL significa "viva".
    nullables = {columna.name for columna in tabla.columns if columna.nullable}
    assert nullables == {"deleted_at"}


def test_la_conversacion_se_indexa_y_referencia_por_su_dueño() -> None:
    """user_id: índice (se consulta por dueño) y FK a NUESTRA tabla de perfiles."""
    tabla = _tabla(Conversation)

    assert tabla.c.user_id.index

    (fk,) = list(tabla.c.user_id.foreign_keys)
    # A user_profiles, no a auth.users: aquella es de Supabase y por eso el
    # perfil no la referencia; esta la crean nuestras propias migraciones.
    assert fk.column.table.name == "user_profiles"
    assert fk.ondelete == "CASCADE"  # borrar la cuenta borra sus conversaciones


def test_declaracion_de_la_tabla_de_mensajes() -> None:
    """Columnas y tipos: texto público sin tope, pasos internos en JSON."""
    tabla = _tabla(Message)

    assert tabla.name == "messages"
    assert {columna.name for columna in tabla.columns} == _COLUMNAS_DE_MENSAJE

    assert isinstance(tabla.c.id.type, Uuid)
    assert tabla.c.id.default is not None
    assert isinstance(tabla.c.sequence.type, Integer)

    # content es TEXT (no VARCHAR(n)): un itinerario largo es una respuesta
    # legítima; acotar la entrada es cosa del borde de la API (HU-2.4).
    assert isinstance(tabla.c.content.type, Text)
    assert not isinstance(tabla.c.content.type, String) or tabla.c.content.type.length is None

    # JSONB en Postgres, JSON en SQLite: la variante hace portable el modelo.
    assert isinstance(tabla.c.tool_steps.type.dialect_impl(_dialecto_sqlite()), JSON)

    # Ninguna admite NULL: los defaults cubren lo no obligatorio.
    assert all(not columna.nullable for columna in tabla.columns)

    (fk,) = list(tabla.c.conversation_id.foreign_keys)
    assert fk.column.table.name == "conversations"
    assert fk.ondelete == "CASCADE"


def _dialecto_sqlite() -> Any:
    from sqlalchemy.dialects import sqlite

    return sqlite.dialect()


def test_el_orden_tiene_una_unique_y_esa_unique_sirve_la_consulta() -> None:
    """(conversation_id, sequence) es único, y ese índice basta: no hay otro."""
    tabla = _tabla(Message)

    uniques = [c for c in tabla.constraints if isinstance(c, UniqueConstraint)]
    assert [[columna.name for columna in c.columns] for c in uniques] == [
        ["conversation_id", "sequence"]
    ]

    # conversation_id NO lleva índice propio: sería un segundo índice con el
    # mismo prefijo que la UNIQUE, pagando escrituras en el camino más caliente
    # del producto sin servir ninguna consulta que aquella no sirva ya.
    assert not tabla.c.conversation_id.index
    assert tabla.indexes == set()


def test_una_secuencia_negativa_esta_prohibida_por_la_base() -> None:
    """El CHECK atrapa el ``MAX(sequence) + 1`` mal hecho sobre una vacía."""
    tabla = _tabla(Message)

    checks = {c.name for c in tabla.constraints if isinstance(c, CheckConstraint)}
    assert "ck_messages_sequence_no_negativo" in checks


def test_el_rol_es_varchar_con_check_y_solo_admite_lo_persistible() -> None:
    """Solo se guardan turnos conversacionales: ni ``system`` ni ``tool``."""
    tabla = _tabla(Message)
    tipo_rol = tabla.c.role.type

    assert isinstance(tipo_rol, Enum)
    assert tipo_rol.native_enum is False  # VARCHAR + CHECK, no ALTER TYPE
    assert tipo_rol.create_constraint is True
    assert set(tipo_rol.enums) == {"user", "assistant"}

    # El system prompt es un archivo versionado (HU-2.2), no una fila; los
    # pasos de tool viven en tool_steps, no como mensajes propios.
    assert "system" not in tipo_rol.enums
    assert "tool" not in tipo_rol.enums


def test_los_roles_persistidos_no_se_separan_de_los_del_proveedor() -> None:
    """Guardia de deriva: MessageRole es un subconjunto EXACTO de llm.Role.

    Son dos enums a propósito (uno dice qué se puede guardar, el otro qué se
    le puede mandar al modelo), pero sus valores deben seguir coincidiendo o
    la traducción de la HU-2.4 tendría que inventarse un mapeo.
    """
    persistibles = {rol.value for rol in MessageRole}
    del_proveedor = {rol.value for rol in Role}

    assert persistibles < del_proveedor


# --------------------------------------------------------------------------
# Comportamiento contra la base
# --------------------------------------------------------------------------


def _conversacion_con_perfil(bd: BaseDeTest) -> uuid.UUID:
    """Crea el perfil dueño y su conversación; devuelve el id de esta."""
    from app.models import UserProfile

    user_id = uuid.uuid4()
    conversacion = Conversation(user_id=user_id, title="Tokio en abril")

    async def ejercicio() -> uuid.UUID:
        async with bd.factory() as session:
            session.add(UserProfile(id=user_id, email=f"{user_id}@example.com"))
            session.add(conversacion)
            await session.commit()
            return conversacion.id

    return bd.run(ejercicio)


def test_crear_una_conversacion_aplica_los_defaults(bd: BaseDeTest) -> None:
    """Nace viva, sin borrar, con sus timestamps puestos por la base."""
    id_conversacion = _conversacion_con_perfil(bd)

    async def ejercicio() -> None:
        async with bd.factory() as session:
            conversacion = (
                await session.execute(
                    select(Conversation).where(Conversation.id == id_conversacion)
                )
            ).scalar_one()

            assert conversacion.title == "Tokio en abril"
            assert conversacion.deleted_at is None
            assert conversacion.is_deleted is False
            assert isinstance(conversacion.created_at, datetime)
            assert isinstance(conversacion.updated_at, datetime)

    bd.run(ejercicio)


def test_los_mensajes_se_leen_en_su_orden_aunque_se_inserten_desordenados(
    bd: BaseDeTest,
) -> None:
    """El orden lo manda ``sequence``, no el orden de INSERT ni ``created_at``.

    Se insertan a propósito 2, 0, 1: si el orden dependiera de la inserción
    —o del timestamp, que en la misma transacción empata— este test saldría
    con la conversación revuelta.
    """
    id_conversacion = _conversacion_con_perfil(bd)

    async def ejercicio() -> list[str]:
        async with bd.factory() as session:
            session.add_all(
                [
                    Message(
                        conversation_id=id_conversacion,
                        role=MessageRole.ASSISTANT,
                        sequence=2,
                        content="tercero",
                    ),
                    Message(
                        conversation_id=id_conversacion,
                        role=MessageRole.USER,
                        sequence=0,
                        content="primero",
                    ),
                    Message(
                        conversation_id=id_conversacion,
                        role=MessageRole.ASSISTANT,
                        sequence=1,
                        content="segundo",
                    ),
                ]
            )
            await session.commit()

        async with bd.factory() as session:
            mensajes = (
                (await session.execute(select_conversation_messages(id_conversacion)))
                .scalars()
                .all()
            )
            return [mensaje.content for mensaje in mensajes]

    assert bd.run(ejercicio) == ["primero", "segundo", "tercero"]


def test_dos_mensajes_en_la_misma_posicion_fallan(bd: BaseDeTest) -> None:
    """La UNIQUE convierte el bug de orden en un error ruidoso, no en un revuelto."""
    id_conversacion = _conversacion_con_perfil(bd)

    async def ejercicio() -> bool:
        async with bd.factory() as session:
            session.add(Message(conversation_id=id_conversacion, role=MessageRole.USER, sequence=0))
            await session.commit()

        async with bd.factory() as session:
            session.add(
                Message(conversation_id=id_conversacion, role=MessageRole.ASSISTANT, sequence=0)
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return True
            return False

    assert bd.run(ejercicio) is True


def test_tool_steps_guarda_una_secuencia_estructurada_y_por_defecto_esta_vacia(
    bd: BaseDeTest,
) -> None:
    """El campo INTERNO acepta JSON anidado y vuelve como lista de dicts.

    Hoy nadie lo llena (las tools son la HU-2.6): se ejerce ahora para que la
    tabla nazca con la forma correcta y no haya que migrar datos después.
    """
    id_conversacion = _conversacion_con_perfil(bd)
    pasos: list[dict[str, Any]] = [
        {
            "tool": "weather",
            "arguments": {"city": "Tokio", "when": "2026-04-10"},
            "result": {"temp_c": 18.5, "condition": "lluvia ligera"},
        },
        {"tool": "weather", "arguments": {"city": "Kioto"}, "result": {"temp_c": 20.0}},
    ]

    async def ejercicio() -> None:
        async with bd.factory() as session:
            session.add(
                Message(
                    conversation_id=id_conversacion,
                    role=MessageRole.USER,
                    sequence=0,
                    content="¿llueve en Tokio?",
                )
            )
            session.add(
                Message(
                    conversation_id=id_conversacion,
                    role=MessageRole.ASSISTANT,
                    sequence=1,
                    content="Llovizna, lleva paraguas.",
                    tool_steps=pasos,
                )
            )
            await session.commit()

        async with bd.factory() as session:
            mensajes = (
                (await session.execute(select_conversation_messages(id_conversacion)))
                .scalars()
                .all()
            )

        pregunta, respuesta = mensajes
        # El turno del usuario no usó herramientas: lista vacía, nunca NULL.
        assert pregunta.tool_steps == []
        # El del asistente conserva la secuencia entera, anidamiento incluido.
        assert respuesta.tool_steps == pasos
        assert respuesta.tool_steps[0]["result"]["condition"] == "lluvia ligera"
        # Y lo público sigue siendo solo el texto.
        assert respuesta.content == "Llovizna, lleva paraguas."

    bd.run(ejercicio)


def test_el_soft_delete_saca_la_conversacion_de_las_vivas(bd: BaseDeTest) -> None:
    """Marcar ``deleted_at`` la esconde sin borrar la fila ni sus mensajes."""
    id_conversacion = _conversacion_con_perfil(bd)

    async def ejercicio() -> None:
        async with bd.factory() as session:
            conversacion = (
                await session.execute(
                    select(Conversation).where(Conversation.id == id_conversacion)
                )
            ).scalar_one()
            user_id = conversacion.user_id

            vivas = (await session.execute(select_live_conversations(user_id))).scalars().all()
            assert [c.id for c in vivas] == [id_conversacion]

            conversacion.deleted_at = datetime.now(UTC)
            await session.commit()

        async with bd.factory() as session:
            vivas = (await session.execute(select_live_conversations(user_id))).scalars().all()
            assert vivas == []

            # La fila sigue ahí: es papelera, no borrado.
            borrada = (
                await session.execute(
                    select(Conversation).where(Conversation.id == id_conversacion)
                )
            ).scalar_one()
            assert borrada.is_deleted is True
            assert isinstance(borrada.deleted_at, datetime)

    bd.run(ejercicio)


def test_las_conversaciones_vivas_son_solo_las_del_dueño(bd: BaseDeTest) -> None:
    """El filtro por ``user_id`` no deja ver el hilo de otra persona."""
    from app.models import UserProfile

    ana, beto = uuid.uuid4(), uuid.uuid4()

    async def ejercicio() -> None:
        async with bd.factory() as session:
            session.add_all(
                [
                    UserProfile(id=ana, email="ana@example.com"),
                    UserProfile(id=beto, email="beto@example.com"),
                    Conversation(user_id=ana, title="de Ana"),
                    Conversation(user_id=beto, title="de Beto"),
                ]
            )
            await session.commit()

        async with bd.factory() as session:
            de_ana = (await session.execute(select_live_conversations(ana))).scalars().all()

        assert [c.title for c in de_ana] == ["de Ana"]

    bd.run(ejercicio)


def test_defaults_del_lado_de_la_base(bd: BaseDeTest) -> None:
    """Un INSERT sin pasar por el ORM también recibe título, texto y pasos."""
    id_conversacion = _conversacion_con_perfil(bd)

    async def ejercicio() -> None:
        conversaciones = _tabla(Conversation)
        mensajes = _tabla(Message)

        async with bd.engine.begin() as conn:
            await conn.execute(
                conversaciones.insert().values(id=uuid.uuid4(), user_id=uuid.uuid4())
            )
            fila_conversacion = (
                await conn.execute(
                    select(conversaciones.c.title, conversaciones.c.deleted_at).where(
                        conversaciones.c.id != id_conversacion
                    )
                )
            ).one()

            await conn.execute(
                mensajes.insert().values(
                    id=uuid.uuid4(),
                    conversation_id=id_conversacion,
                    role="user",
                    sequence=0,
                )
            )
            fila_mensaje = (
                await conn.execute(select(mensajes.c.content, mensajes.c.tool_steps))
            ).one()

        assert fila_conversacion.title == ""  # server_default '', nunca NULL
        assert fila_conversacion.deleted_at is None  # nace viva
        assert fila_mensaje.content == ""
        assert fila_mensaje.tool_steps == []  # server_default '[]', nunca NULL

    bd.run(ejercicio)


def test_un_rol_que_no_se_persiste_se_rechaza_en_las_DOS_capas(bd: BaseDeTest) -> None:
    """``system`` no entra: lo para el tipo en Python y lo para el CHECK de la base.

    Son dos defensas distintas y las dos importan. ``validate_strings=True``
    hace que SQLAlchemy rechace el valor ANTES de mandar el INSERT (falla en el
    proceso, con el nombre del enum en el mensaje); el CHECK es el respaldo para
    lo que llegue por SQL crudo o por otro cliente, que es justo por lo que la
    regla vive en la base y no solo en el modelo.
    """
    id_conversacion = _conversacion_con_perfil(bd)

    async def por_el_tipo() -> bool:
        async with bd.factory() as session:
            # Una cadena cruda en vez de MessageRole: es lo que llegaría de
            # un JSON sin validar. El __init__ declarativo no la tipa, así que
            # mypy no la para — la para el tipo de la columna, en runtime.
            session.add(Message(conversation_id=id_conversacion, role="system", sequence=0))
            try:
                await session.commit()
            except StatementError:
                await session.rollback()
                return True
            return False

    async def por_el_check_de_la_base() -> bool:
        # Por SQL crudo, esquivando la validación del tipo, para ejercer la
        # constraint de verdad.
        try:
            async with bd.engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, sequence) "
                        "VALUES (:id, :conversacion, 'system', 0)"
                    ),
                    {"id": str(uuid.uuid4()), "conversacion": str(id_conversacion)},
                )
        except IntegrityError:
            return True
        return False

    assert bd.run(por_el_tipo) is True
    assert bd.run(por_el_check_de_la_base) is True
