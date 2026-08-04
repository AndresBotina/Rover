"""Identificador de petición, propagado sin pasarlo a mano (HU-1.12).

El problema: para que TODA línea de log de una petición se pueda correlacionar,
el id tiene que llegar hasta el último `logger.warning(...)` de un servicio
—que está a varias llamadas de distancia del middleware que lo generó—. Pasarlo
como argumento obligaría a que cada función intermedia lo aceptara y lo
reenviara: contamina firmas que no tienen nada que ver con logs, y basta que
alguien lo olvide para perder la traza.

La solución es un ``ContextVar``. Cada petición corre en su propia *task* de
asyncio, y cada task hereda una copia del contexto: lo que el middleware escriba
aquí lo ven todas las llamadas de ESA petición, y solo de esa —peticiones
concurrentes no se pisan, a diferencia de una variable global o de un atributo
de módulo. Un ``Filter`` de logging lo lee (``app/core/logging.py``), así que
nadie tiene que acordarse de nada al loguear.

No usamos ``request.state`` por lo mismo: obliga a tener el ``Request`` a mano,
y los servicios (``app/services/auth.py``) no lo tienen ni deberían.
"""

import re
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from typing import Any

from starlette.requests import Request

# Cabecera estándar de facto. Se lee de la petición (si un proxy o el cliente
# ya trae un id, se respeta para poder cruzar los logs de ambos sistemas) y se
# devuelve siempre en la respuesta.
REQUEST_ID_HEADER = "X-Request-ID"

# Un id ENTRANTE viene de fuera, así que es entrada no confiable: acaba en
# cada línea de log y en una cabecera de respuesta. Se acota a un alfabeto y a
# una longitud seguros; cualquier otra cosa se descarta y se genera uno propio.
# Sin esto: un salto de línea permitiría FALSIFICAR líneas de log enteras (log
# injection), y un valor de 10 KB engordaría todas las líneas de la petición.
_ID_ACEPTABLE = re.compile(r"\A[A-Za-z0-9._:-]{1,64}\Z")

_request_id: ContextVar[str | None] = ContextVar("rover_request_id", default=None)


def new_request_id() -> str:
    """Genera un id de petición nuevo."""
    return uuid.uuid4().hex


def sanitize_request_id(value: str | None) -> str | None:
    """Devuelve el id entrante si es seguro de propagar; si no, ``None``."""
    if value is None:
        return None
    candidato = value.strip()
    return candidato if _ID_ACEPTABLE.match(candidato) else None


def set_request_id(value: str) -> Token[str | None]:
    """Fija el id de la petición en curso. Devuelve el token para restaurarlo."""
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restaura el valor anterior (el middleware lo hace al terminar)."""
    _request_id.reset(token)


def get_request_id() -> str | None:
    """Id de la petición en curso, o ``None`` fuera de una (arranque, apagado)."""
    return _request_id.get()


# --- Segundo canal: el scope ASGI --------------------------------------------
# El ContextVar cubre el 99% (todo lo que corre DENTRO del middleware), pero no
# el handler de los 500: Starlette monta su ``ServerErrorMiddleware`` como el
# más externo de todos, así que cuando una excepción llega hasta él, el
# middleware de contexto ya ejecutó su ``finally`` y restauró la variable. Ese
# handler sí tiene el ``Request``, y el scope es el MISMO objeto de principio a
# fin de la petición: guardar ahí el id lo hace recuperable sin depender de
# cuándo se restaura el contexto.


def store_request_id(scope: MutableMapping[str, Any], value: str) -> None:
    """Deja el id en el scope ASGI (visible luego como ``request.state``)."""
    estado = scope.setdefault("state", {})
    estado["request_id"] = value


def request_id_of(request: Request) -> str | None:
    """Id de una petición concreta: primero el scope, luego el contexto."""
    almacenado = getattr(request.state, "request_id", None)
    if isinstance(almacenado, str):
        return almacenado
    return get_request_id()
