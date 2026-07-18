"""Baseline del esquema: punto de partida SIN tablas.

Decisión (HU-1.2): los modelos de dominio llegan en HU-1.10 (usuarios), así
que esta revisión no crea tablas a propósito — solo ancla el versionado
(al aplicarse, Alembic crea su tabla de control ``alembic_version``). Las
próximas migraciones (``--autogenerate``) parten de este estado conocido.

Revision ID: cbee92b21376
Revises:
Create Date: 2026-07-18 10:38:15.227616

"""

from collections.abc import Sequence

# Identificadores de revisión usados por Alembic.
revision: str = "cbee92b21376"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline: no crea nada (los modelos llegan en HU-1.10)."""


def downgrade() -> None:
    """Coherente con upgrade: no hay nada que revertir."""
