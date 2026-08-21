"""Formato de los Server-Sent Events de la API (HU-2.4).

Aquí vive UNA cosa: cómo se serializa un evento en el cable. El contenido de
los eventos lo decide cada endpoint (hoy solo el chat), pero la FORMA se fija
en un sitio, igual que ``core/errors.py`` fija la forma de los errores HTTP.


## Un solo ``data:`` con JSON, y NO el campo ``event:`` del estándar

SSE permite nombrar el evento con una línea ``event: delta`` aparte del
``data:``. Aquí no se usa, y la alternativa elegida es un campo ``type``
DENTRO del JSON. Dos razones:

1. **Nadie va a consumir esto con ``EventSource``.** La API del navegador solo
   sabe hacer GET y no deja poner cabeceras, así que no puede mandar ni el
   cuerpo del mensaje ni el ``Authorization: Bearer`` (HU-1.6). Web y móvil
   consumen el stream con ``fetch`` y parsean los marcos a mano
   (``@rover/shared``), donde el nombre del evento no aporta nada que no dé el
   discriminante.
2. **Un solo sitio del que fiarse.** Con ``event:`` y ``type`` habría dos
   fuentes para lo mismo y podrían discrepar. Con el discriminante dentro del
   JSON, el type guard de TypeScript ramifica por el mismo campo que existe en
   el cable — el mismo criterio que el contrato discriminado de la HU-1.3b.

El JSON se serializa **sin saltos de línea reales** (``json.dumps`` los escapa
como ``\\n``), así que un evento siempre cabe en una línea ``data:`` y no hace
falta partirlo. Eso no es casualidad del formato: es la razón por la que el
contenido viaja como JSON y no como texto crudo, donde un salto de línea del
modelo habría partido el marco en dos.


## El error de la HU-1.8, adaptado a SSE

Cuando el fallo llega DESPUÉS de las cabeceras ya no hay status HTTP que
devolver: la respuesta empezó siendo un 200. El error se emite entonces como
un evento más, con **el mismo cuerpo** que tendría en HTTP —``code``,
``message``, ``details``, ``error_id``— envuelto en ``{"type": "error", ...}``.
El cliente ramifica por el mismo catálogo de ``code`` que ya conoce; lo único
que cambia es por dónde llegó.
"""

import json
from typing import Any

from app.core.errors import ErrorBody, ErrorCode

#: Tipo MIME del stream. El ``charset`` es explícito: los mensajes llevan
#: acentos y emojis, y un intermediario que asuma latin-1 los rompería.
SSE_MEDIA_TYPE = "text/event-stream; charset=utf-8"

#: Cabeceras que hacen que el stream llegue TROZO A TROZO hasta el navegador.
#: Sin ellas la respuesta funciona igual… pero entera y al final, que es
#: exactamente lo que esta HU existe para evitar (ver README § Streaming SSE).
SSE_HEADERS: dict[str, str] = {
    # ``no-cache`` para el navegador y cualquier caché intermedia.
    # ``no-transform`` es la parte que se olvida: prohíbe a los proxies
    # recomprimir o reempaquetar el cuerpo, que es como un intermediario acaba
    # bufferizando un stream sin querer.
    "Cache-Control": "no-cache, no-transform",
    # Convención de SSE sobre HTTP/1.1. En HTTP/2 la cabecera no existe (está
    # prohibida) y el propio protocolo ya multiplexa sin cerrar la conexión;
    # mandarla no molesta y ayuda a los proxies antiguos que sí la miran.
    "Connection": "keep-alive",
    # Específica de nginx (y de todo lo que lo lleva por dentro): apaga el
    # buffer de respuesta para ESTA respuesta. Es la diferencia entre ver el
    # texto aparecer y verlo llegar de golpe al final.
    "X-Accel-Buffering": "no",
}


def sse_event(payload: dict[str, Any]) -> str:
    """Serializa un evento como un marco SSE (``data: {...}`` + línea en blanco).

    ``ensure_ascii=False`` para que el cable lleve UTF-8 de verdad (un acento
    ocupa un carácter, no seis) y ``separators`` sin espacios porque el stream
    del chat manda un marco por cada trozo de texto: los bytes de adorno se
    pagan miles de veces por conversación.
    """
    cuerpo = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {cuerpo}\n\n"


def sse_error_event(
    code: ErrorCode,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    error_id: str | None = None,
) -> str:
    """Evento de error con el MISMO cuerpo que el contrato HTTP de la HU-1.8.

    Se construye a partir de ``ErrorBody`` y no de un diccionario a mano: así
    un campo nuevo en el contrato de errores aparece aquí solo, sin que nadie
    tenga que acordarse de este archivo.
    """
    body = ErrorBody(code=code, message=message, details=details, error_id=error_id)
    return sse_event({"type": "error", "error": body.model_dump(mode="json")})
