"""Entorno de Alembic para el engine ASYNC del proyecto.

Reutiliza la configuración real del backend: la URL sale de ROVER_DATABASE_URL
(app.core.config, SecretStr) y la construcción del engine reusa build_async_url
y engine_kwargs de app.core.database — incluida la detección del Transaction
Pooler de Supabase (sin prepared statements, NullPool). La URL JAMÁS se escribe
en alembic.ini: ese archivo se versiona y la URL es un secreto.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base, build_async_url, engine_kwargs

config = context.config

# Logging según alembic.ini (solo logging; la URL nunca vive ahí).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata de los modelos (heredan de Base): habilita --autogenerate.
# Los modelos de dominio llegan en HU-1.10; bastará con importar sus módulos
# aquí cuando existan para que Alembic los compare contra la base.
target_metadata = Base.metadata


def _database_url() -> URL:
    """Resuelve la URL async desde la config (fail-fast si no está)."""
    if settings.database_url is None:
        raise RuntimeError(
            "ROVER_DATABASE_URL no está configurada: Alembic la necesita para "
            "migrar. Defínela en apps/backend/.env (ver .env.example)."
        )
    return build_async_url(settings.database_url.get_secret_value())


def run_migrations_offline() -> None:
    """Modo offline: emite el SQL sin conectarse (p. ej. alembic upgrade --sql)."""
    context.configure(
        url=_database_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Crea el engine async con los MISMOS kwargs que la app y migra."""
    url = _database_url()
    connectable = create_async_engine(url, **engine_kwargs(url))

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Modo online: conecta y aplica las migraciones."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
