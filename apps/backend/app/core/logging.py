"""Configuración mínima de logging de la aplicación.

Problema que resuelve: uvicorn configura SUS loggers (``uvicorn``,
``uvicorn.access``, ``uvicorn.error``) pero deja el resto sin handler. Los
loggers de la app (``app.*``, vía ``logging.getLogger(__name__)``) quedaban
apoyados en el ``lastResort`` de ``logging`` — que solo emite ``WARNING`` y
superiores, a ``stderr``, sin formato, y desaparece en cuanto cualquier
librería añade un handler a un ancestro. Resultado: los diagnósticos de la app
eran invisibles al depurar.

Aquí enganchamos un handler propio al logger raíz de la app (``app``) que
escribe a ``stdout`` con un formato consistente, para que sus mensajes salgan
junto a los de uvicorn tanto en local como en contenedor. ``propagate`` se deja
activo (no se duplican líneas: al haber un handler en ``app`` el ``lastResort``
no se dispara, y el root no tiene handlers en producción), lo que además
permite que ``caplog`` capture en los tests.

Es lo MÍNIMO para que los logs sean visibles y útiles ahora; el logging
estructurado (JSON, request-id) sigue siendo la HU-1.12.
"""

import logging
import sys
from typing import TextIO

_APP_LOGGER = "app"
_FORMAT = "%(levelname)s [%(name)s] %(message)s"

# Handler que instala esta función; se recuerda para no duplicarlo al
# reconfigurar (p. ej. entre tests).
_installed_handler: logging.Handler | None = None


def configure_logging(*, level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Enruta los loggers ``app.*`` a ``stream`` (por defecto ``stdout``).

    Idempotente: reemplaza el handler anterior instalado por esta función en
    vez de acumular handlers. ``stream`` es inyectable para poder verificar en
    tests que los mensajes se emiten de verdad.
    """
    global _installed_handler

    logger = logging.getLogger(_APP_LOGGER)
    logger.setLevel(level)
    logger.propagate = True

    if _installed_handler is not None:
        logger.removeHandler(_installed_handler)

    handler: logging.Handler = logging.StreamHandler(sys.stdout if stream is None else stream)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    _installed_handler = handler
