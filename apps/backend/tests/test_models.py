"""Tests del modelo de perfil de usuario — SIN base real (CI sin Supabase).

El esquema se crea desde ``Base.metadata`` sobre SQLite async en memoria (el
mismo sustituto que en ``test_database.py``). Los tipos exclusivos de
Postgres están resueltos en el propio modelo: ``preferences`` es JSONB con
variante JSON para SQLite (``with_variant``), el ``id`` usa el ``sa.Uuid``
genérico (UUID nativo en Postgres, texto en SQLite) y ``plan`` es
VARCHAR + CHECK (no ENUM nativo), idéntico en ambas bases.
"""

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import Enum, String, Table, Uuid, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models import Plan, UserProfile

_COLUMNAS_ESPERADAS = {"id", "email", "plan", "preferences", "created_at", "updated_at"}


def _tabla() -> Table:
    """La Table del modelo (``__table__`` se tipa como FromClause; se estrecha)."""
    tabla = UserProfile.__table__
    assert isinstance(tabla, Table)
    return tabla


async def _engine_con_esquema() -> AsyncEngine:
    """SQLite async en memoria con las tablas de Base.metadata creadas."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def test_declaracion_de_la_tabla() -> None:
    """Tabla, columnas y tipos: perfil sin credenciales, con id de Supabase."""
    tabla = _tabla()

    assert tabla.name == "user_profiles"
    # Exactamente estas columnas: NO hay contraseñas ni credenciales (viven
    # en Supabase Auth).
    assert {columna.name for columna in tabla.columns} == _COLUMNAS_ESPERADAS

    # El id es el de Supabase: clave primaria UUID y SIN default propio.
    assert [columna.name for columna in tabla.primary_key.columns] == ["id"]
    assert isinstance(tabla.c.id.type, Uuid)
    assert tabla.c.id.default is None
    assert tabla.c.id.server_default is None

    assert isinstance(tabla.c.email.type, String)
    assert tabla.c.email.index

    # Ninguna columna admite NULL (los defaults cubren lo no obligatorio).
    assert all(not columna.nullable for columna in tabla.columns)


def test_plan_es_varchar_con_check_y_default_free() -> None:
    """El plan guarda valores ("free"), sin ENUM nativo de Postgres."""
    tabla = _tabla()
    tipo_plan = tabla.c.plan.type

    assert isinstance(tipo_plan, Enum)
    assert tipo_plan.native_enum is False  # VARCHAR + CHECK, no ALTER TYPE
    assert tipo_plan.create_constraint is True
    assert set(tipo_plan.enums) == {plan.value for plan in Plan}
    assert tabla.c.plan.server_default is not None


def test_crear_y_leer_un_perfil() -> None:
    """Alta y lectura contra la base sustituta, con los defaults aplicados."""

    async def ejercicio() -> None:
        engine = await _engine_con_esquema()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        id_supabase = uuid.uuid4()

        async with factory() as session:
            session.add(UserProfile(id=id_supabase, email="ana@example.com"))
            await session.commit()

        async with factory() as session:
            perfil = (
                await session.execute(select(UserProfile).where(UserProfile.id == id_supabase))
            ).scalar_one()

            assert perfil.email == "ana@example.com"
            assert perfil.plan is Plan.FREE
            assert perfil.preferences == {}
            assert isinstance(perfil.created_at, datetime)
            assert isinstance(perfil.updated_at, datetime)

        await engine.dispose()

    asyncio.run(ejercicio())


def test_defaults_del_lado_de_la_base() -> None:
    """Un INSERT sin pasar por el ORM también recibe plan y preferences."""

    async def ejercicio() -> None:
        engine = await _engine_con_esquema()
        tabla = _tabla()

        async with engine.begin() as conn:
            await conn.execute(tabla.insert().values(id=uuid.uuid4(), email="core@example.com"))
            fila = (await conn.execute(select(tabla.c.plan, tabla.c.preferences))).one()

        assert fila.plan == "free"  # server_default del CHECK-enum
        assert fila.preferences == {}  # server_default '{}', nunca NULL

        await engine.dispose()

    asyncio.run(ejercicio())
