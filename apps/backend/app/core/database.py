"""Capa de acceso a datos: SQLAlchemy 2.0 async + asyncpg (Supabase Postgres).

La URL vive en config TAL CUAL la entrega Supabase (``postgresql://…``); aquí
se le cambia el driver al async (``postgresql+asyncpg://``) al crear el engine.

El engine es PEREZOSO: se crea en el primer uso, no al importar. Así la app
arranca en local/test sin base configurada (usarla sin configurar falla con un
error claro) y el pool se cierra limpiamente en el lifespan (dispose_engine).
"""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from sqlalchemy import URL, NullPool, make_url
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


def is_supabase_pooler(url: URL) -> bool:
    """True si la URL apunta al Transaction Pooler de Supabase (Supavisor).

    Se DERIVA de la propia URL (host del pooler o su puerto 6543) a propósito:
    sin flag manual, cambiar la URL nunca puede dejar una config incoherente.
    """
    host = url.host or ""
    return "pooler.supabase.com" in host or url.port == 6543


def engine_kwargs(url: URL) -> dict[str, Any]:
    """Argumentos del engine según el tipo de conexión (pooler vs directa)."""
    if is_supabase_pooler(url):
        # ---- Transaction Pooler de Supabase (Supavisor) ---------------------
        # Usamos el pooler porque la conexión directa de Supabase resuelve a
        # IPv6, sin salida IPv6 ni en local ni en Render; el pooler da IPv4.
        #
        # El pooler en modo transacción reparte cada petición a CUALQUIER
        # conexión física del pool: dos consultas seguidas pueden caer en
        # conexiones distintas. Los PREPARED STATEMENTS que asyncpg usa por
        # defecto viven en una conexión concreta, así que contra el pooler
        # rompen ("prepared statement … does not exist" o nombres duplicados).
        # Este es el ajuste ESTÁNDAR documentado por SQLAlchemy y Supabase:
        # desactivar ambas cachés de prepared statements y dar nombre único a
        # los statements efímeros. El costo de rendimiento es despreciable
        # para esta app. Es 100% REVERSIBLE: con una URL de conexión directa
        # esta rama no se ejecuta y todo vuelve al comportamiento por defecto.
        return {
            # El pooling real ya lo hace Supavisor: NullPool evita apilar un
            # segundo pool que retenga slots del pooler con conexiones ociosas
            # de larga vida (abrir contra el pooler es barato: él mantiene las
            # conexiones calientes hacia Postgres). pre_ping sobra sin pool.
            "poolclass": NullPool,
            "connect_args": {
                "statement_cache_size": 0,  # caché nativa de asyncpg
                "prepared_statement_cache_size": 0,  # caché del dialecto SQLAlchemy
                "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
            },
        }
    # Conexión directa: comportamiento original de HU-1.1.
    return {
        # Pool moderado: Supabase (plan free) limita las conexiones directas.
        "pool_size": 5,
        "max_overflow": 5,
        # Detecta conexiones muertas antes de entregarlas (Supabase las
        # recicla tras inactividad).
        "pool_pre_ping": True,
    }


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
        url = build_async_url(settings.database_url.get_secret_value())
        _engine = create_async_engine(url, **engine_kwargs(url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Devuelve la fábrica de sesiones async (creada una sola vez)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI: entrega una AsyncSession por request.

    El ``async with`` garantiza que la sesión se cierra al terminar el request,
    incluso si el endpoint lanza una excepción.

    Se anota como ``AsyncGenerator`` y no como ``AsyncIterator`` porque quien la
    itera A MANO (sin ``Depends``) necesita poder cerrarla: ``aclosing`` exige
    un ``aclose()``, que solo el primer tipo promete.
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
