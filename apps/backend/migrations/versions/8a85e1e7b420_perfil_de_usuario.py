"""Perfil de usuario (HU-1.10a): tabla ``user_profiles``.

Perfil local que COMPLEMENTA a Supabase Auth: el ``id`` es el mismo de
``auth.users`` (sin default: lo pone la app al crear el perfil) y no hay
contraseñas ni credenciales. Sin FK a ``auth.users`` a propósito — ese
esquema lo gestiona el tooling de Supabase; la integridad es responsabilidad
de la app (ver ``app/models/user.py``). El plan es VARCHAR + CHECK (no ENUM
nativo) para poder evolucionarlo con migraciones normales.

Revision ID: 8a85e1e7b420
Revises: cbee92b21376
Create Date: 2026-07-18 14:31:00.192885

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Identificadores de revisión usados por Alembic.
revision: str = "8a85e1e7b420"
down_revision: str | Sequence[str] | None = "cbee92b21376"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea ``user_profiles`` con su índice por email."""
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "plan",
            sa.Enum("free", "pro", name="plan", native_enum=False, create_constraint=True),
            server_default="free",
            nullable=False,
        ),
        # JSONB a secas: la variante JSON para SQLite vive solo en el modelo
        # (los tests crean el esquema desde Base.metadata, no con migraciones).
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_profiles_email"), "user_profiles", ["email"], unique=False)


def downgrade() -> None:
    """Elimina ``user_profiles`` (el CHECK del plan cae con la tabla)."""
    op.drop_index(op.f("ix_user_profiles_email"), table_name="user_profiles")
    op.drop_table("user_profiles")
