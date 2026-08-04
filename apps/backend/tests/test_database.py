"""Tests de la capa de base de datos y de /v1/health/db — SIN base real.

El CI no tiene Supabase, así que la base real se SUSTITUYE en cada test:
monkeypatch de ``app.core.database.get_session_factory`` para que entregue
sesiones de SQLite async en memoria (aiosqlite) o falle a propósito. La
conectividad real contra Supabase se verifica a mano con GET /v1/health/db
(ver README del backend).
"""

import pytest
from anyio.abc import BlockingPortal
from fastapi.testclient import TestClient
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import database
from app.core.database import build_async_url, engine_kwargs, get_db, is_supabase_pooler
from app.main import app
from tests.conftest import BaseDeTest

_URL_POOLER = "postgresql://postgres.abc:pw@aws-1-us-east-1.pooler.supabase.com:6543/postgres"
_URL_DIRECTA = "postgresql://postgres:pw@db.proyecto.supabase.co:5432/postgres"


def test_build_async_url_anade_el_driver_async() -> None:
    """La URL se guarda como la da Supabase; el driver lo añade el código."""
    url = build_async_url("postgresql://postgres:secreto@db.proyecto.supabase.co:5432/postgres")

    assert url.drivername == "postgresql+asyncpg"
    # El resto de la URL queda intacto.
    assert url.username == "postgres"
    assert url.password == "secreto"
    assert url.host == "db.proyecto.supabase.co"
    assert url.port == 5432
    assert url.database == "postgres"


def test_detecta_pooler_por_host_o_puerto() -> None:
    assert is_supabase_pooler(build_async_url(_URL_POOLER))
    # Puerto 6543 basta, aunque el host no sea el típico del pooler.
    assert is_supabase_pooler(build_async_url("postgresql://u:p@otro-host:6543/db"))
    assert not is_supabase_pooler(build_async_url(_URL_DIRECTA))


def test_url_de_pooler_desactiva_prepared_statements() -> None:
    """Contra el Transaction Pooler, asyncpg no debe cachear prepared statements."""
    kwargs = engine_kwargs(build_async_url(_URL_POOLER))

    connect_args = kwargs["connect_args"]
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_cache_size"] == 0
    # Nombres únicos para los statements efímeros (recomendación SQLAlchemy/Supabase).
    nombre = connect_args["prepared_statement_name_func"]()
    assert nombre.startswith("__asyncpg_")
    # El pooling lo hace Supavisor: sin segundo pool en SQLAlchemy.
    assert kwargs["poolclass"] is NullPool


def test_url_directa_mantiene_comportamiento_por_defecto() -> None:
    kwargs = engine_kwargs(build_async_url(_URL_DIRECTA))

    assert "connect_args" not in kwargs
    assert "poolclass" not in kwargs
    assert kwargs["pool_pre_ping"] is True


def test_el_engine_acepta_los_kwargs_del_pooler(loop_de_test: BlockingPortal) -> None:
    """create_async_engine debe aceptar los nombres de los kwargs (sin conectar)."""
    url = build_async_url(_URL_POOLER)
    engine = create_async_engine(url, **engine_kwargs(url))
    loop_de_test.call(engine.dispose)


def test_get_db_entrega_y_cierra_la_sesion(bd: BaseDeTest, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_db entrega una AsyncSession usable y la cierra al agotarse."""
    closed = False
    original_close = AsyncSession.close

    async def close_espia(self: AsyncSession) -> None:
        nonlocal closed
        closed = True
        await original_close(self)

    monkeypatch.setattr(AsyncSession, "close", close_espia)

    async def ejercicio() -> None:
        generador = get_db()
        session = await anext(generador)

        assert isinstance(session, AsyncSession)
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

        # FastAPI agota el generador al terminar el request; aquí lo simulamos.
        with pytest.raises(StopAsyncIteration):
            await anext(generador)

    bd.run(ejercicio)
    assert closed, "la sesión debe cerrarse cuando el request termina"


def test_health_db_ok_con_base_sustituta(bd: BaseDeTest) -> None:
    with TestClient(app) as client:
        response = client.get("/v1/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_error_responde_503_sin_filtrar_secretos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Base caída o sin configurar → 503 tipado, sin credenciales en el cuerpo."""

    def factory_rota() -> async_sessionmaker[AsyncSession]:
        # Simula el fallo real (config ausente / conexión rechazada) con un
        # mensaje que CONTIENE un secreto: no debe llegar al cliente.
        raise RuntimeError("postgresql://postgres:password-secreta@db.x.supabase.co")

    monkeypatch.setattr(database, "get_session_factory", factory_rota)

    with TestClient(app) as client:
        response = client.get("/v1/health/db")

    assert response.status_code == 503
    # Desde la HU-1.8 el fallo sale con el formato ÚNICO de error, no con un
    # cuerpo propio de la sonda: el cliente parsea todos los errores igual.
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "No se pudo conectar a la base de datos.",
            "details": None,
            "error_id": None,
        }
    }
    assert "password-secreta" not in response.text
