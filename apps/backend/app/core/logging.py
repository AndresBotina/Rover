"""Configuración de logging de la app: estructurado (JSON) o legible (HU-1.12).

Empezó en la HU-1.3b resolviendo un problema concreto: uvicorn configura SUS
loggers (``uvicorn``, ``uvicorn.access``, ``uvicorn.error``) pero deja el resto
sin handler, así que los loggers de la app (``app.*``) quedaban apoyados en el
``lastResort`` de ``logging`` —solo ``WARNING``+, a stderr, sin formato— y los
diagnósticos eran invisibles. Aquí se les engancha un handler propio a stdout.

La HU-1.12 añade lo que faltaba para operar en producción:

- **Dos formatos, uno por audiencia.** En producción, JSON de una línea por
  registro: lo que consume una herramienta de monitoreo, que necesita filtrar
  por campo (``request_id``, ``level``, ``status``) y no sabe leer prosa. En
  local, texto: quien lee es una persona con una terminal, y un JSON por línea
  es hostil para eso. ``ROVER_LOG_FORMAT`` fuerza cualquiera de los dos.
- **Contexto sin pasarlo a mano.** Un ``Filter`` inyecta el id de la petición
  (``app/core/request_context.py``) en CADA registro, venga de donde venga. Los
  call sites no cambian: ``logger.warning("...")`` ya sale correlacionado.
- **Los logs de uvicorn, coherentes.** Sus loggers se reenganchan a este mismo
  handler, para que en producción no salgan líneas de texto suelto entre el
  JSON. ``uvicorn.access`` se apaga porque su línea la sustituye la de
  ``RequestContextMiddleware``, que dice lo mismo y además trae id y duración.

Qué NO hace este módulo: decidir qué se loguea. La regla de no filtrar secretos
(contraseñas, llaves, tokens, la URL de la base con su contraseña) se cumple en
los call sites, y está cubierta por tests.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Literal, TextIO

from app.core.request_context import get_request_id

LogFormat = Literal["json", "text"]

_APP_LOGGER = "app"

# Loggers de uvicorn que se reenganchan a nuestro handler para que todo salga
# con el mismo formato. ``uvicorn.access`` NO está: se silencia aparte.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
_UVICORN_ACCESS_LOGGER = "uvicorn.access"

# Atributos que ``logging`` pone en TODO registro. Lo que aparezca fuera de
# esta lista llegó por ``extra={...}`` en el call site y es contexto que hay
# que emitir (``status``, ``duration_ms``, ``error_id``…).
_ATRIBUTOS_ESTANDAR = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# Handler que instaló esta función; se recuerda para no acumular handlers al
# reconfigurar (p. ej. entre tests).
_installed_handler: logging.Handler | None = None


class RequestIdFilter(logging.Filter):
    """Cuelga el id de la petición en curso de cada registro.

    Va en el HANDLER y no en un logger concreto: así cubre por igual a los
    loggers de la app y a los de uvicorn, sin repetir el enganche.

    Un ``extra={"request_id": ...}`` explícito MANDA sobre el contexto: es como
    logea el handler de los 500, que corre cuando el contexto ya se restauró.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = get_request_id()
        return True


# Extras que NO se emiten: ``request_id`` va como campo propio, y
# ``color_message`` es el duplicado con códigos ANSI que uvicorn adjunta a sus
# líneas para pintarlas en consola — en el JSON solo sería ruido con escapes.
_EXTRAS_IGNORADOS = frozenset({"request_id", "color_message"})


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    """Campos que el call site añadió con ``extra=``."""
    return {
        clave: valor
        for clave, valor in record.__dict__.items()
        if clave not in _ATRIBUTOS_ESTANDAR
        and clave not in _EXTRAS_IGNORADOS
        and not clave.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Un objeto JSON por línea, listo para una herramienta de monitoreo."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # ISO 8601 en UTC: comparable entre instancias sin pensar en husos.
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        payload.update(_extras(record))

        if record.exc_info:
            tipo, excepcion, _ = record.exc_info
            payload["exception"] = {
                "type": tipo.__name__ if tipo else None,
                "message": str(excepcion) if excepcion else None,
                # La traza SÍ va al log (aquí es donde tiene que estar); lo que
                # nunca sale al cliente es esto (HU-1.8).
                "traceback": self.formatException(record.exc_info),
            }

        # ``default=str`` para que un valor no serializable degrade a su repr
        # en vez de tumbar el logging; ``ensure_ascii=False`` para no convertir
        # los acentos de los mensajes en escapes ilegibles.
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Formato legible para desarrollo, con el id de la petición al final.

    El id va abreviado (8 caracteres): en una terminal, 32 caracteres de UUID
    por línea tapan el mensaje, y 8 bastan para seguir una petición a ojo. El id
    COMPLETO está en la cabecera de la respuesta y en el JSON de producción.
    """

    def __init__(self) -> None:
        super().__init__("%(levelname)s [%(name)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        request_id = getattr(record, "request_id", None)
        if not request_id:
            return base
        return f"{base}  (req {str(request_id)[:8]})"


def _formatter(log_format: LogFormat) -> logging.Formatter:
    return JsonFormatter() if log_format == "json" else TextFormatter()


def configure_logging(
    *,
    level: int = logging.INFO,
    stream: TextIO | None = None,
    log_format: LogFormat | None = None,
) -> None:
    """Enruta los loggers de la app (y los de uvicorn) a ``stream``.

    ``log_format`` por defecto lo decide el ambiente (ver
    ``Settings.effective_log_format``). Idempotente: reemplaza el handler
    anterior instalado por esta función en vez de acumular handlers.
    ``stream`` es inyectable para poder verificar en tests que los mensajes se
    emiten de verdad y con la forma esperada.
    """
    # Import local: este módulo lo usa ``create_app`` antes que nada y config
    # arrastra la validación de todos los settings; mantenerlo perezoso evita
    # atar el orden de importación entre ambos.
    from app.core.config import settings

    global _installed_handler

    formato = log_format if log_format is not None else settings.effective_log_format

    handler: logging.Handler = logging.StreamHandler(sys.stdout if stream is None else stream)
    handler.setLevel(level)
    handler.setFormatter(_formatter(formato))
    handler.addFilter(RequestIdFilter())

    for nombre in [_APP_LOGGER, *_UVICORN_LOGGERS]:
        logger = logging.getLogger(nombre)
        logger.setLevel(level)
        if _installed_handler is not None:
            logger.removeHandler(_installed_handler)
        logger.addHandler(handler)
        # Los de uvicorn dejan de propagar al root (donde uvicorn les puso su
        # propio handler): si no, cada línea saldría dos veces y en dos
        # formatos. El de la app SÍ propaga: no hay handler en el root en
        # producción, no se duplica nada, y así ``caplog`` sigue capturando.
        logger.propagate = nombre == _APP_LOGGER

    # El access log de uvicorn se apaga: RequestContextMiddleware emite una
    # línea equivalente por petición que además trae el id y la duración, y
    # tener las dos sería ruido duplicado con distinto formato.
    acceso = logging.getLogger(_UVICORN_ACCESS_LOGGER)
    acceso.handlers.clear()
    acceso.propagate = False

    _installed_handler = handler
