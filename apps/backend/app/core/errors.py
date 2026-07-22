"""Contrato ÚNICO de error de la API y los handlers que lo aplican (HU-1.8).

Toda respuesta de error —de cualquier endpoint, de la validación de FastAPI o
de un fallo no previsto— sale con la MISMA forma:

    {
      "error": {
        "code": "email_already_exists",     # estable, legible por máquina
        "message": "Ya existe una cuenta…", # seguro de mostrar al usuario
        "details": {...} | null,            # estructura opcional por caso
        "error_id": "9f2c1ab4e77d" | null   # solo en los 500, para el log
      }
    }

Por qué así:

- **Sobre `error`, no plano.** Un único envoltorio hace que el cliente
  distinga "esto es un error" de "esto es un recurso" sin mirar el status ni
  adivinar por las claves; un solo type guard en `@rover/shared` cubre toda
  la API.
- **`code` además del status HTTP.** El status agrupa demasiado: 422 es
  "contraseña débil", "email inválido" y "preferencias demasiado grandes" a la
  vez. El cliente necesita ramificar por algo estable que no cambie al
  reescribir un mensaje ni al traducirlo. Es también donde encajan los
  discriminantes que ya existían: el "email sin confirmar" del 403 ya NO es un
  campo especial dentro de `detail`, es `code == "email_not_confirmed"` — el
  mismo mecanismo que todos los demás errores.
- **`message` para humanos**, siempre seguro: nunca lleva diagnóstico del
  proveedor, de la base ni de la excepción.
- **`details` solo cuando aporta estructura** (los errores campo a campo de la
  validación). Es un objeto, no una lista, para poder crecer sin romper.
- **`error_id` solo en los 500**: el cliente ve un identificador opaco y el
  servidor loguea ESE mismo id junto a la causa real. Es el único puente entre
  lo que ve el usuario y la traza, sin filtrar nada.

Los endpoints lanzan ``ApiError`` (semántica), nunca construyen respuestas de
error: la FORMA se decide aquí y en un solo sitio.
"""

import logging
import uuid
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Campos cuyo valor NUNCA debe aparecer en la respuesta de error.
_SENSITIVE_FIELDS = frozenset({"password"})


class ErrorCode(StrEnum):
    """Catálogo de códigos estables. Añadir uno es parte del contrato público.

    Son del DOMINIO, no del proveedor: los ``error_code`` crudos de Supabase
    (``over_email_send_rate_limit``, ``email_exists``…) se traducen a estos y
    NUNCA se exponen. Filtrarlos ataría a los clientes al proveedor —el mismo
    acoplamiento que el servicio de auth existe para contener— y revelaría qué
    hay detrás de la API sin dar nada a cambio.
    """

    # Autenticación / autorización.
    UNAUTHENTICATED = "unauthenticated"  # 401 uniforme del middleware
    INVALID_CREDENTIALS = "invalid_credentials"  # 401 del login
    EMAIL_NOT_CONFIRMED = "email_not_confirmed"  # 403
    FORBIDDEN = "forbidden"  # 403 genérico

    # Recursos y conflictos.
    NOT_FOUND = "not_found"  # 404
    METHOD_NOT_ALLOWED = "method_not_allowed"  # 405
    EMAIL_ALREADY_EXISTS = "email_already_exists"  # 409
    CONFLICT = "conflict"  # 409 genérico

    # Entrada rechazada (422).
    VALIDATION_ERROR = "validation_error"  # forma del cuerpo (Pydantic)
    WEAK_PASSWORD = "weak_password"
    INVALID_EMAIL = "invalid_email"
    PREFERENCES_TOO_LARGE = "preferences_too_large"

    # Límites y disponibilidad.
    RATE_LIMITED = "rate_limited"  # 429
    SERVICE_UNAVAILABLE = "service_unavailable"  # 503
    INTERNAL_ERROR = "internal_error"  # 500

    # Cualquier HTTPException sin código propio (red de seguridad).
    HTTP_ERROR = "http_error"


# Mensaje del 500: idéntico SIEMPRE. Lo que cambia es el error_id.
_INTERNAL_ERROR_MESSAGE = (
    "Ocurrió un error inesperado. Si el problema persiste, reporta este identificador."
)

# Código por defecto de una HTTPException que no nació como ApiError (las que
# levanta el propio framework: ruta inexistente, método no permitido…).
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHENTICATED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_422_UNPROCESSABLE_CONTENT: ErrorCode.VALIDATION_ERROR,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
}

# Mensajes propios para los errores que levanta el framework: los suyos vienen
# en inglés ("Not Found") y el resto de la API responde en español.
_STATUS_TO_MESSAGE: dict[int, str] = {
    status.HTTP_404_NOT_FOUND: "El recurso solicitado no existe.",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Método no permitido para esta ruta.",
}


class ErrorBody(BaseModel):
    """Contenido del error (lo que va bajo la clave ``error``)."""

    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None
    error_id: str | None = None


class ErrorResponse(BaseModel):
    """Cuerpo de CUALQUIER respuesta de error de la API."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "email_already_exists",
                        "message": "Ya existe una cuenta con ese email.",
                        "details": None,
                        "error_id": None,
                    }
                }
            ]
        }
    )

    error: ErrorBody


class ApiError(Exception):
    """Error de la API con su status, su código estable y su mensaje.

    Lo lanzan los endpoints y las dependencias; el handler lo convierte en la
    respuesta. Frente a ``HTTPException``, obliga a elegir un ``code`` del
    catálogo en vez de dejar que el cliente deduzca del status.
    """

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_doc(description: str) -> dict[str, Any]:
    """Entrada de ``responses=`` para documentar un error en OpenAPI (HU-1.9)."""
    return {"model": ErrorResponse, "description": description}


def _render(
    status_code: int,
    code: ErrorCode,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    error_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Construye la ÚNICA forma de respuesta de error de la API."""
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details, error_id=error_id)
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """``ApiError`` → respuesta: el endpoint ya eligió status, código y mensaje."""
    if not isinstance(exc, ApiError):  # pragma: no cover - invariante de registro
        raise exc
    return _render(
        exc.status_code,
        exc.code,
        exc.message,
        details=exc.details,
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Red de seguridad para las ``HTTPException`` que no nacieron como ``ApiError``.

    Son las del propio framework (ruta inexistente → 404, método no permitido
    → 405) y las de cualquier dependencia de terceros. Se les asigna un código
    por status y un mensaje propio; si el status no está en el catálogo se
    conserva su ``detail`` solo cuando es texto plano, y si es una estructura se
    descarta —antes un mensaje genérico que arriesgar filtrar algo no previsto.
    """
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - invariante
        raise exc
    code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.HTTP_ERROR)
    generico = "La petición no pudo completarse."
    message = _STATUS_TO_MESSAGE.get(
        exc.status_code, exc.detail if isinstance(exc.detail, str) else generico
    )
    headers = getattr(exc, "headers", None)
    return _render(exc.status_code, code, message, headers=headers)


def _toca_campo_sensible(error: dict[str, Any]) -> bool:
    """True si el error se refiere a un campo sensible (por ``loc`` o por ``input``)."""
    loc = error.get("loc", ())
    if any(str(parte) in _SENSITIVE_FIELDS for parte in loc):
        return True
    # Errores a nivel del cuerpo entero (p. ej. JSON inválido, campo extra):
    # el ``input`` es el objeto completo y podría contener la contraseña.
    entrada = error.get("input")
    return isinstance(entrada, dict) and bool(_SENSITIVE_FIELDS & entrada.keys())


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 de validación dentro del formato único, SIN eco de campos sensibles.

    Pydantic añade a cada error el valor recibido (``input``). Para la
    contraseña eso la copiaría al cuerpo de la respuesta — y de ahí podría
    acabar en logs de acceso, proxies o la consola del navegador. Se elimina
    ``input`` en los errores que tocan un campo sensible; el resto del error
    (tipo, ubicación, mensaje) se conserva intacto bajo ``details.errors``.

    ``exc`` se tipa como ``Exception`` (lo que exige ``add_exception_handler``);
    en la práctica solo se registra para ``RequestValidationError``.
    """
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - invariante
        raise exc

    saneados: list[dict[str, Any]] = []
    for error in exc.errors():
        if _toca_campo_sensible(error):
            error = {clave: valor for clave, valor in error.items() if clave != "input"}
        saneados.append(error)
    return _render(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_ERROR,
        "Hay campos inválidos en la petición.",
        details={"errors": jsonable_encoder(saneados)},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Último cortafuegos: NADA de una excepción no prevista llega al cliente.

    El cuerpo es siempre el mismo mensaje genérico más un ``error_id`` opaco.
    Ese id —y solo ahí— se loguea junto al tipo, el mensaje y la traza de la
    excepción, que es donde pueden aparecer credenciales (la URL de la base con
    su contraseña, una llave, un token) y por eso no salen del servidor.

    Se registran el método y la ruta, no la query string ni las cabeceras: un
    token en `Authorization` no debe acabar en los logs.
    """
    error_id = uuid.uuid4().hex[:12]
    logger.exception(
        "Error no controlado [error_id=%s] en %s %s", error_id, request.method, request.url.path
    )
    return _render(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorCode.INTERNAL_ERROR,
        _INTERNAL_ERROR_MESSAGE,
        error_id=error_id,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Engancha los cuatro handlers que producen el formato único.

    El de ``Exception`` va al final por claridad, pero el orden no importa:
    Starlette elige por tipo, del más específico al más general.
    """
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
