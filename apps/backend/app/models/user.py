"""Modelo de PERFIL de usuario (no de identidad).

La identidad vive en Supabase Auth (``auth.users``): esta tabla solo guarda lo
que la app necesita del usuario (plan, preferencias). Por eso aquí NO hay
contraseñas ni credenciales, y el ``id`` no se genera nunca en este lado: es
el MISMO id que Supabase asignó al usuario.

Sin ForeignKey a ``auth.users`` A PROPÓSITO: una FK cross-schema acoplaría
nuestras migraciones al esquema interno de Supabase (gestionado por su
tooling, que puede recrearlo) y rompería en cualquier base sin ese esquema
(SQLite en tests). La integridad la garantiza la aplicación: el perfil se
crea de forma idempotente a partir de un usuario que YA existe en Supabase
(estrategia de consistencia de la HU-1.3).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Plan(enum.StrEnum):
    """Plan del usuario; decide sus límites de uso (rate limiting, HU-1.7)."""

    FREE = "free"
    PRO = "pro"


# VARCHAR + CHECK en vez del ENUM nativo de Postgres: añadir un plan es
# reemplazar la constraint en una migración normal (el ENUM nativo exige
# ALTER TYPE y no deja quitar valores), y el CHECK funciona igual en SQLite
# (tests). values_callable guarda los VALORES ("free"), no los nombres.
_PlanEnum = Enum(
    Plan,
    name="plan",
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
    values_callable=lambda e: [miembro.value for miembro in e],
)

# En Postgres: JSONB (indexable, operadores nativos). En SQLite (tests): el
# JSON genérico. La migración usa JSONB a secas porque solo corre en Postgres.
_PreferencesJSON = JSONB().with_variant(JSON(), "sqlite")


class UserProfile(Base):
    """Perfil local del usuario; complementa a Supabase Auth, no lo reemplaza."""

    __tablename__ = "user_profiles"

    # El MISMO id de auth.users. Sin default a propósito: olvidar pasarlo debe
    # fallar en vez de inventar una identidad que Supabase no conoce.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)

    # Copia de conveniencia para consultar; la fuente de verdad es Supabase.
    email: Mapped[str] = mapped_column(String(320), index=True)

    plan: Mapped[Plan] = mapped_column(_PlanEnum, default=Plan.FREE, server_default=Plan.FREE.value)

    # Preferencias de viaje; objeto vacío por defecto, nunca NULL.
    preferences: Mapped[dict[str, Any]] = mapped_column(
        _PreferencesJSON, default=dict, server_default=text("'{}'")
    )

    # Timestamps puestos por la BASE (server_default / onupdate con now()),
    # no por el reloj de la app.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
