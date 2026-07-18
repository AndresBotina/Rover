"""Capa de acceso a datos: SQLAlchemy 2.0 async + asyncpg (Supabase Postgres).

La URL vive en config TAL CUAL la entrega Supabase (``postgresql://…``); aquí
se le cambia el driver al async (``postgresql+asyncpg://``) al crear el engine.

El engine es PEREZOSO: se crea en el primer uso, no al importar. Así la app
arranca en local/test sin base configurada (usarla sin configurar falla con un
error claro) y el pool se cierra limpiamente en el lifespan (dispose_engine).
"""

from collections.abc import AsyncIterator

from sqlalchemy import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Base declarativa para los modelos de dominio (llegan desde HU-1.10)."""


def build_async_url(database_url: str) -> URL:
    """Cambia el driver de la URL tal-como-la-da-Supabase al async (asyncpg)."""
    return make_url(database_url).set(drivername="postgresql+asyncpg")


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Devuelve el engine async, creándolo la primera vez que se necesita."""
    global _engine
    if _engine is None:
        if settings.database_url is None:
            raise RuntimeError(
                "ROVER_DATABASE_URL no está configurada. Defínela en apps/backend/.env "
                "(local) o en Render → Environment (producción); ver .env.example."
            )
        _engine = create_async_engine(
            build_async_url(settings.database_url.get_secret_value()),
            # Pool moderado: Supabase (plan free) limita las conexiones directas.
            pool_size=5,
            max_overflow=5,
            # Detecta conexiones muertas antes de entregarlas (Supabase las
            # recicla tras inactividad).
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Devuelve la fábrica de sesiones async (creada una sola vez)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dependencia de FastAPI: entrega una AsyncSession por request.

    El ``async with`` garantiza que la sesión se cierra al terminar el request,
    incluso si el endpoint lanza una excepción.
    """
    async with get_session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    """Cierra el pool del engine al apagar la app (no-op si nunca se usó)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
