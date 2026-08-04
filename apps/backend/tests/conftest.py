"""Fixtures compartidas por toda la suite.

Dos cosas viven aquí porque son transversales y porque tenerlas repetidas en
cada módulo ya causó problemas:

1. **Aislamiento del rate limiting** (desde la HU-1.7): el contador vive en la
   memoria del proceso y sobrevive entre tests, así que sin reiniciarlo un
   módulo agotaría el cupo del siguiente y haría fallar tests que no tienen
   nada que ver con los límites.

2. **La base de datos de test** (HU-1.13, deuda de la Épica 1). Antes cada
   módulo montaba la suya con ``asyncio.run(...)``, y eso repartía el MISMO
   engine entre tres o cuatro event loops distintos: uno para crear el esquema,
   el del ``TestClient`` para las peticiones, otro por cada consulta de
   verificación y otro más para el ``dispose``. Como el pool por defecto
   (``AsyncAdaptedQueuePool``) **reutiliza conexiones**, una conexión abierta
   bajo un loop acababa usándose —o cerrándose— bajo otro que ya no existía, y
   el hilo trabajador de aiosqlite fallaba al entregar su resultado con
   ``RuntimeError: Event loop is closed``. El warning aparecía de forma
   intermitente y **en el test que estuviera corriendo en ese momento**, no en
   el que lo causaba.

   La solución tiene tres piezas, y hacen falta las tres:

   - **``NullPool``**: ninguna conexión se guarda para reutilizarse, así que
     ninguna sobrevive al loop que la abrió. Es la raíz del problema; sin esto,
     centralizar el fixture solo cambia de sitio el reparto entre loops.
   - **Un único loop propio del fixture** (un ``BlockingPortal``) donde el
     engine nace, se crea el esquema, se hacen las consultas de verificación y
     se cierra. Nadie vuelve a llamar a ``asyncio.run(...)``: ese era el patrón
     que fabricaba un loop nuevo y lo tiraba a los pocos milisegundos.
   - **Fichero temporal, no ``:memory:``**: con ``NullPool`` cada conexión es
     nueva, y una base en memoria sería una base VACÍA distinta por conexión
     (el clásico "no such table"). Antes esto funcionaba de milagro, porque el
     pool reciclaba la única conexión que tenía el esquema. El fichero también
     evita el ``StaticPool``, que arreglaría lo del esquema volviendo a
     compartir una conexión entre loops — justo lo que queremos quitar.
"""

import os
import tempfile
from collections.abc import Awaitable, Callable, Iterator
from typing import TypeVar

import anyio.from_thread
import pytest
from anyio.abc import BlockingPortal
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core import database
from app.core.rate_limit import reset_rate_limit_store

T = TypeVar("T")


@pytest.fixture(autouse=True)
def rate_limit_aislado() -> None:
    """Cada test arranca con el contador de peticiones vacío."""
    reset_rate_limit_store()


@pytest.fixture
def loop_de_test() -> Iterator[BlockingPortal]:
    """Un único event loop, vivo durante todo el test, para el código async.

    Sustituye a los ``asyncio.run(...)`` sueltos: aquel patrón creaba un loop
    por llamada y lo cerraba al volver, dejando atrás objetos —conexiones,
    futures— que seguían apuntando a un loop muerto.
    """
    with anyio.from_thread.start_blocking_portal("asyncio") as portal:
        yield portal


class BaseDeTest:
    """La base de un test y la forma de consultarla desde código síncrono."""

    def __init__(
        self,
        engine: AsyncEngine,
        factory: async_sessionmaker[AsyncSession],
        portal: BlockingPortal,
    ) -> None:
        #: Para lo que necesita ir por debajo del ORM (INSERT del core, DDL).
        self.engine = engine
        self.factory = factory
        self._portal = portal

    def run(self, funcion: Callable[[], Awaitable[T]]) -> T:
        """Ejecuta una corutina en el loop del test y devuelve su resultado.

        Es el reemplazo de ``asyncio.run(...)``: mismo uso desde un test
        síncrono, pero sin fabricar (ni cerrar) un event loop cada vez. Recibe
        una función SIN argumentos porque todos los usos son closures que ya
        capturan lo que necesitan.
        """
        return self._portal.call(funcion)


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch, loop_de_test: BlockingPortal) -> Iterator[BaseDeTest]:
    """Base SQLite del test, ya con el esquema y enchufada a la app.

    Un fichero temporal POR TEST: el aislamiento entre tests es el mismo que
    había (cada uno arrancaba su propia base), sin estado compartido.
    ``get_session_factory`` queda apuntando aquí, así que la app —a través de
    ``get_db``— usa esta base sin saberlo.
    """
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def crear_esquema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)

    loop_de_test.call(crear_esquema)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)

    yield BaseDeTest(engine, factory, loop_de_test)

    # El engine muere en el MISMO loop en el que nació.
    loop_de_test.call(engine.dispose)
    os.unlink(path)
