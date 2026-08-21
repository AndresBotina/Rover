"""Conversaciones y mensajes (HU-2.3): tablas ``conversations`` y ``messages``.

La memoria del agente. Dos tablas: el hilo y sus turnos. El endpoint que las
llena es la HU-2.4; ``tool_steps`` nace vacío y lo llenará la HU-2.6.

Detalles que NO son de autogenerate y conviene tener a mano al revisar:

- **FK a ``user_profiles.id``, y sí es distinto del caso de ``auth.users``.**
  Aquel esquema es de Supabase (ajeno, ausente en SQLite) y por eso el perfil
  no lo referencia; ``user_profiles`` la crea esta misma cadena de migraciones,
  así que aquí la FK no acopla nada que no controlemos. ``ON DELETE CASCADE``
  en ambas: borrar la cuenta se lleva sus conversaciones, y purgar una
  conversación se lleva sus mensajes.
- **``role`` es VARCHAR + CHECK**, no el ENUM nativo de Postgres — mismo
  criterio que ``plan`` en la revisión anterior: añadir un rol (``tool``, si
  algún día los pasos se guardan como filas) es reemplazar una constraint en
  una migración normal, no un ``ALTER TYPE``.
- **UNIQUE (conversation_id, sequence)**: el orden dentro de una conversación
  es un invariante, no una convención. Ese índice sirve además la consulta
  "los mensajes de esta conversación, en orden", y por eso ``conversation_id``
  NO lleva un índice propio: sería un segundo índice con el mismo prefijo.
- **JSONB a secas** en ``tool_steps``: la variante JSON para SQLite vive solo
  en el modelo (los tests crean el esquema desde ``Base.metadata``, no con
  migraciones), igual que ``preferences`` en la revisión anterior.

Revision ID: e98b4722e99b
Revises: 8a85e1e7b420
Create Date: 2026-08-20 19:45:13.712044

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Identificadores de revisión usados por Alembic.
revision: str = "e98b4722e99b"
down_revision: str | Sequence[str] | None = "8a85e1e7b420"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea ``conversations`` (con su índice por dueño) y ``messages``."""
    op.create_table(
        "conversations",
        # Id propio (no viene de fuera); lo genera la app antes del INSERT.
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # Cadena vacía por defecto, nunca NULL: una sola forma de decir
        # "sin título".
        sa.Column("title", sa.String(length=120), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # SOFT-DELETE: la ÚNICA columna nullable de las dos tablas, y lo es
        # porque NULL *significa* algo aquí: la conversación sigue viva.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # "Las conversaciones de este usuario" es la consulta de la pantalla de
    # inicio: sin este índice sería un seq scan sobre toda la tabla.
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user", "assistant", name="message_role", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        # Orden estable dentro de la conversación (0-based). No se ordena por
        # created_at: en Postgres ``now()`` es la hora de inicio de la
        # TRANSACCIÓN, así que pregunta y respuesta escritas juntas empatan.
        sa.Column("sequence", sa.Integer(), nullable=False),
        # PÚBLICO: el texto que ve el cliente. Sin longitud máxima.
        sa.Column("content", sa.Text(), server_default=sa.text("''"), nullable=False),
        # INTERNO: pasos del tool-calling (HU-2.6). Nunca se expone al cliente.
        sa.Column(
            "tool_steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_messages_sequence_no_negativo"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_messages_conversation_sequence"
        ),
    )


def downgrade() -> None:
    """Elimina ambas tablas; ``messages`` primero, por la FK que la ata.

    Los CHECK, la UNIQUE y los índices caen con su tabla; el índice del dueño
    se suelta explícito para dejar simétrico lo que ``upgrade`` creó explícito.
    """
    op.drop_table("messages")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_table("conversations")
