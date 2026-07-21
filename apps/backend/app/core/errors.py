"""Manejo transversal de errores de la API.

Por ahora: sanea los errores de validación para que el valor de un campo
SENSIBLE (la contraseña) no se devuelva al cliente.
"""

from typing import Any

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Campos cuyo valor NUNCA debe aparecer en la respuesta de error.
_SENSITIVE_FIELDS = frozenset({"password"})


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
    """422 estándar de FastAPI, pero SIN eco del valor de campos sensibles.

    Pydantic añade a cada error el valor recibido (``input``). Para la
    contraseña eso la copiaría al cuerpo de la respuesta 422 — y de ahí podría
    acabar en logs de acceso, proxies o la consola del navegador. Se elimina
    ``input`` en los errores que tocan un campo sensible; el resto del error
    (tipo, ubicación, mensaje) se conserva intacto.

    ``exc`` se tipa como ``Exception`` (lo que exige ``add_exception_handler``);
    en la práctica solo se registra para ``RequestValidationError``.
    """
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - invariante de registro
        raise exc

    saneados: list[dict[str, Any]] = []
    for error in exc.errors():
        if _toca_campo_sensible(error):
            error = {clave: valor for clave, valor in error.items() if clave != "input"}
        saneados.append(error)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(saneados)},
    )
