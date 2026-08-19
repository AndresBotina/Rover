"""Implementación del proveedor para DeepSeek (endpoint OpenAI-compatible).

Es la PRIMERA implementación concreta de ``LLMProvider``, no la única posible:
todo lo específico de DeepSeek —la forma del cuerpo, el formato del stream, sus
códigos de error— está encerrado en este archivo. El resto del backend habla
con ``base.LLMProvider`` y no importa nada de aquí (ni siquiera este módulo:
el que instancia es ``registry.py``).


## Integración elegida: httpx directo, NO el SDK de OpenAI

El endpoint de DeepSeek es compatible con la API de OpenAI, así que el SDK
oficial (``openai``, apuntado a otra ``base_url``) era la alternativa obvia.
Se descartó por cuatro motivos, en orden de peso:

1. **Traduciríamos dos veces.** El SDK devuelve sus propios modelos Pydantic
   (``ChatCompletion``, ``ChatCompletionChunk``) y nosotros los convertiríamos
   acto seguido a los tipos de ``base.py`` — que es justo lo que este módulo
   hace ya desde el JSON crudo. La capa intermedia no aporta un paso: aporta
   uno de más.
2. **Los campos que más nos importan no están en sus tipos.** El acierto de
   caché de DeepSeek viaja en ``prompt_cache_hit_tokens``, que no existe en el
   esquema de OpenAI; con el SDK habría que bajarse a los campos extra igual
   que aquí, pero sorteando un modelo tipado que dice que no están. Esa métrica
   es media razón de ser de la instrumentación de esta HU.
3. **Control del parseo de errores.** Queremos traducir a las excepciones de
   ``errors.py`` mirando status + ``error.code``, no desempacar la jerarquía de
   excepciones del SDK (``APIStatusError``, ``RateLimitError``…) para volver a
   empaquetarla. Mismo criterio, y mismo resultado, que en ``services/auth.py``
   con GoTrue frente a ``supabase-py``.
4. **Dependencia cero.** ``httpx`` ya está en el proyecto (lo usan el cliente
   de Supabase Auth y el ``TestClient`` de FastAPI) y su async es real: no
   bloquea el event loop, que es requisito de un backend async de punta a punta
   como este. El SDK usa ``httpx`` por debajo, así que en lo técnico no
   traería nada nuevo, solo otro paquete que versionar.

Lo que se renuncia con esta decisión, dicho claro: reintentos automáticos y el
parseo de SSE que el SDK trae hechos. El parseo del stream son las pocas líneas
de ``_dato_sse`` (el formato es texto plano y está fijado por el estándar
SSE), y los reintentos son una política que preferimos decidir nosotros en la
HU-2.4 —reintentar un stream a medias no es lo mismo que reintentar un POST—.


## Compatibilidad con otros proveedores

Como el cuerpo y el stream son los de la API OpenAI-compatible, esta misma
clase sirve para cualquier proveedor que la implemente (OpenRouter, Together,
un vLLM propio): basta cambiar ``ROVER_LLM_BASE_URL``, ``ROVER_LLM_MODEL`` y la
key. El path del endpoint se CONCATENA a la URL base, así que una base con
sufijo (``https://openrouter.ai/api/v1``) también funciona. Lo único
propietario que se lee es ``prompt_cache_hit_tokens``, y su ausencia degrada
sola: sin ese campo, el acierto de caché se reporta como 0.


## Razonamiento DESACTIVADO por defecto (non-think)

DeepSeek V4 razona por defecto, con esfuerzo alto, y ese razonamiento **se
factura como salida**. Medido contra el proveedor real, una respuesta
conversacional de cuatro frases costaba **~1.163 tokens de salida y ~15 s**,
de los que el usuario veía una fracción mínima. Para el chat de Rover —"¿qué
llevo a Cartagena?"— eso es pagar y hacer esperar por deliberación que no
mejora la respuesta. Por eso el cuerpo lleva ``thinking: {"type": "disabled"}``
salvo que la config diga otra cosa (``ROVER_LLM_THINKING``).

Tres consecuencias que conviene tener presentes:

1. **No llega ``reasoning_content``.** El parseo nunca dependió de él —lee
   ``message.content`` y ``delta.content``, y un campo extra se ignora—, así
   que reactivar el razonamiento no rompe nada: solo vuelven a aparecer
   eventos de stream sin texto mientras el modelo piensa.
2. **``temperature`` y ``top_p`` vuelven a contar.** En modo razonamiento
   DeepSeek los ignora; en non-think mandan otra vez, así que el
   ``ROVER_LLM_TEMPERATURE`` de la config (0.7) pasa a tener efecto real sobre
   la variedad de las respuestas.
3. **Ojo con reactivarlo en la HU-2.6 (tool-calling).** Con el razonamiento
   activado, DeepSeek EXIGE que las peticiones multi-turno con tools devuelvan
   el ``reasoning_content`` del turno anterior, o responde 400. Hoy eso no nos
   afecta —está desactivado—, pero quien reactive ``thinking`` tendrá que
   preservar ese campo en la persistencia de los pasos intermedios (HU-2.3) y
   reenviarlo en el loop de tools. No es un detalle menor: se descubre con un
   400 en la segunda vuelta del loop, no en la primera.
"""

import json
import logging
import time
from collections.abc import AsyncGenerator, Iterable, Sequence
from contextlib import aclosing
from typing import Any, Final, Literal

import httpx

from app.services.llm.base import (
    Capability,
    Completion,
    CompletionChunk,
    Message,
    Usage,
)
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMError,
    LLMProviderError,
    LLMQuotaExceeded,
    LLMRateLimited,
    LLMUnavailable,
)
from app.services.llm.instrumentation import Outcome, log_llm_call
from app.services.llm.prompt import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

#: Nombre del proveedor en la instrumentación (agrupa la serie por proveedor).
PROVIDER_NAME: Final = "deepseek"

#: Ruta del endpoint, relativa a ``ROVER_LLM_BASE_URL``.
_CHAT_PATH: Final = "/chat/completions"

#: Marca de fin del stream SSE en la API OpenAI-compatible.
_SSE_DONE: Final = "[DONE]"

#: Modo de razonamiento pedido al proveedor. ``provider_default`` no manda el
#: campo (ver ``_payload``); los otros dos viajan como ``{"type": ...}``.
ThinkingMode = Literal["disabled", "enabled", "provider_default"]

#: Valor de ``llm_thinking`` que significa "no mandes el campo".
_THINKING_OMITIDO: Final = "provider_default"

#: Mensajes SEGUROS para el usuario (los detalles del proveedor van al log).
_MSG_UNAVAILABLE: Final = "El asistente no está disponible en este momento; inténtalo de nuevo."
_MSG_RATE_LIMITED: Final = "El asistente está saturado; inténtalo de nuevo en unos segundos."
_MSG_REJECTED: Final = "No se pudo procesar la consulta."
_MSG_INTERNAL: Final = "El asistente no pudo responder."


class DeepSeekProvider:
    """``LLMProvider`` sobre la API de DeepSeek.

    No lee ``settings`` por su cuenta: recibe todo por constructor. Así el
    módulo es probable sin tocar variables de entorno, y quien decide la
    configuración es un solo sitio (``registry.py``).

    ``transport`` existe para los tests: un ``httpx.MockTransport`` permite
    ejercer el camino REAL —construcción del cuerpo, cabeceras, parseo del
    stream, traducción de errores— contra respuestas simuladas, sin red y sin
    key. Un mock del método ``complete`` no probaría nada de eso.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        thinking: ThinkingMode = "disabled",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout_seconds
        self._thinking = thinking
        self._transport = transport

    # --- Contrato de LLMProvider ---------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> frozenset[Capability]:
        """Solo texto. DeepSeek V4 Flash no procesa imágenes.

        Declararlo es lo que hace que el seam por capacidad de ``registry.py``
        pueda enrutar de verdad el día que exista un segundo proveedor, en vez
        de asumir que cualquiera sirve para todo.
        """
        return frozenset({Capability.TEXT})

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> Completion:
        payload = self._payload(
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            stream=False,
        )
        inicio = time.perf_counter()
        resultado: Outcome = "error"
        error: str | None = None
        completion: Completion | None = None

        try:
            body = await self._post(payload)
            completion = _parse_completion(body, fallback_model=self._model)
            resultado = "ok"
            return completion
        except LLMError as exc:
            error = type(exc).__name__
            raise
        finally:
            log_llm_call(
                provider=PROVIDER_NAME,
                model=completion.model if completion else self._model,
                capability=Capability.TEXT,
                streaming=False,
                outcome=resultado,
                duration_ms=_ms_desde(inicio),
                usage=completion.usage if completion else None,
                finish_reason=completion.finish_reason if completion else None,
                message_count=len(payload["messages"]),
                context_chars=_context_chars(payload["messages"]),
                error=error,
            )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncGenerator[CompletionChunk]:
        """Reexpone el stream de DeepSeek como el async generator de la interfaz.

        El chunk final del proveedor llega SIN texto y con el consumo (se pide
        con ``stream_options.include_usage``): se emite igual, para que la
        instrumentación y la HU-2.8 tengan los tokens también en streaming.
        Sin ese flag, el camino de streaming sería un agujero ciego en las
        métricas justo en el que va a ser el camino normal del producto.
        """
        payload = self._payload(
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            stream=True,
        )
        inicio = time.perf_counter()
        primer_trozo: float | None = None
        resultado: Outcome = "error"
        error: str | None = None
        usage: Usage | None = None
        finish_reason: str | None = None
        modelo = self._model

        try:
            # ``aclosing``: si quien consume abandona el ``async for``, el
            # generador de abajo se cierra AQUÍ y con él la conexión HTTP, en
            # vez de quedar suspendido hasta que pase el recolector. Es la
            # misma lección que dejó la fuga de sesiones de la HU-1.7.
            async with aclosing(self._post_stream(payload)) as eventos:
                async for evento in eventos:
                    trozo, modelo_evento = _parse_chunk(evento, fallback_model=modelo)
                    modelo = modelo_evento
                    if trozo.usage is not None:
                        usage = trozo.usage
                    if trozo.finish_reason is not None:
                        finish_reason = trozo.finish_reason
                    if trozo.text and primer_trozo is None:
                        primer_trozo = _ms_desde(inicio)
                    yield trozo
            resultado = "ok"
        except LLMError as exc:
            error = type(exc).__name__
            raise
        except GeneratorExit:
            # El consumidor abandonó el stream (p. ej. el cliente SSE se fue).
            # No es un fallo del proveedor, pero los tokens ya se gastaron: se
            # registra aparte para no ensuciar la tasa de errores.
            resultado = "cancelled"
            raise
        finally:
            log_llm_call(
                provider=PROVIDER_NAME,
                model=modelo,
                capability=Capability.TEXT,
                streaming=True,
                outcome=resultado,
                duration_ms=_ms_desde(inicio),
                time_to_first_chunk_ms=primer_trozo,
                usage=usage,
                finish_reason=finish_reason,
                message_count=len(payload["messages"]),
                context_chars=_context_chars(payload["messages"]),
                error=error,
            )

    # --- Transporte ----------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        """Cliente HTTP para UNA llamada.

        Se crea y se cierra por llamada, como en ``services/auth.py``: un
        cliente compartido a nivel de módulo queda atado al event loop en el
        que nació, y esa clase de acoplamiento ya costó cara en los tests de la
        Épica 1 (ver el docstring de ``tests/conftest.py``). El precio es un
        handshake TLS por llamada, despreciable frente a los cientos de
        milisegundos que tarda un modelo en responder; si algún día deja de
        serlo, el punto de cambio es este método y un cliente en el lifespan de
        la app.
        """
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST no-streaming; devuelve el cuerpo 2xx ya validado como objeto."""
        try:
            async with self._client() as client:
                response = await client.post(_CHAT_PATH, json=payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(_MSG_UNAVAILABLE) from exc

        if response.status_code >= 400:
            raise _translate_error(response.status_code, _cuerpo_json(response.text))

        body = _cuerpo_json(response.text)
        if body is None:
            raise LLMProviderError(_MSG_INTERNAL, provider_status=response.status_code)
        return body

    async def _post_stream(self, payload: dict[str, Any]) -> AsyncGenerator[dict[str, Any]]:
        """POST en streaming; emite cada evento del SSE ya deserializado.

        El error puede llegar ANTES del stream (status >= 400: se lee el cuerpo
        completo y se traduce igual que en el camino no-streaming) o A MITAD
        (la conexión se corta: ``httpx`` levanta y se traduce a
        ``LLMUnavailable``).
        """
        try:
            async with self._client() as client:
                async with client.stream("POST", _CHAT_PATH, json=payload) as response:
                    if response.status_code >= 400:
                        # El cuerpo de error sí viene completo y de una vez;
                        # hay que leerlo explícitamente porque la respuesta se
                        # abrió en modo stream.
                        await response.aread()
                        raise _translate_error(response.status_code, _cuerpo_json(response.text))

                    async for linea in response.aiter_lines():
                        datos = _dato_sse(linea)
                        if datos is None:
                            continue
                        if datos == _SSE_DONE:
                            return
                        evento = _cuerpo_json(datos)
                        if evento is None:
                            # Un evento ilegible no justifica tirar una
                            # respuesta que ya va por la mitad en la pantalla
                            # del usuario: se descarta y se sigue.
                            logger.warning("Evento del stream del LLM ilegible; se descarta")
                            continue
                        yield evento
        except httpx.HTTPError as exc:
            raise LLMUnavailable(_MSG_UNAVAILABLE) from exc

    # --- Cuerpo de la petición -----------------------------------------------

    def _payload(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str | None,
        temperature: float | None,
        max_output_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        """Arma el cuerpo, con el system prompt SIEMPRE de primero.

        Ese orden es el prefijo estable del que vive el caché automático de
        DeepSeek (ver ``base.py``): el prompt no se mezcla con el historial ni
        depende de lo que mande el llamador. Cuando la HU-2.6 traiga las
        definiciones de tools, irán justo detrás del prompt y antes del
        historial, por la misma razón.

        ``thinking`` es lo único de aquí que NO es de la API de OpenAI: es la
        extensión propietaria con la que DeepSeek activa o apaga el
        razonamiento. Su forma —``{"type": "disabled"}``, no un booleano ni una
        cadena suelta— vive en este módulo y no sale de él, igual que
        ``prompt_cache_hit_tokens``: fuera se habla de "modo de razonamiento",
        que es lo que un proveedor distinto expresaría a su manera
        (``reasoning_effort``, ``reasoning: {...}``). Por eso también existe
        ``provider_default``: un proveedor OpenAI-compatible que no conozca el
        campo y rechace parámetros desconocidos se atiende cambiando entorno,
        sin tocar este archivo.
        """
        prompt = DEFAULT_SYSTEM_PROMPT if system_prompt is None else system_prompt
        cuerpo: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt},
                *({"role": m.role.value, "content": m.content} for m in messages),
            ],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": (
                self._max_output_tokens if max_output_tokens is None else max_output_tokens
            ),
            "stream": stream,
        }
        if self._thinking != _THINKING_OMITIDO:
            cuerpo["thinking"] = {"type": self._thinking}
        if stream:
            # Sin esto, el stream NO reporta tokens y la instrumentación del
            # camino principal quedaría vacía.
            cuerpo["stream_options"] = {"include_usage": True}
        return cuerpo


# --- Traducción de errores ---------------------------------------------------

# status HTTP → (excepción de dominio, mensaje SEGURO para el cliente).
# Se traduce por STATUS, que es el dato estable de una API HTTP, y no buscando
# palabras en el mensaje del proveedor — misma regla que en ``services/auth.py``.
_STATUS_A_DOMINIO: dict[int, tuple[type[LLMError], str]] = {
    400: (LLMBadRequest, _MSG_REJECTED),
    401: (LLMAuthError, _MSG_UNAVAILABLE),
    402: (LLMQuotaExceeded, _MSG_UNAVAILABLE),
    403: (LLMAuthError, _MSG_UNAVAILABLE),
    404: (LLMBadRequest, _MSG_REJECTED),
    422: (LLMBadRequest, _MSG_REJECTED),
    429: (LLMRateLimited, _MSG_RATE_LIMITED),
}


def _translate_error(status_code: int, body: dict[str, Any] | None) -> LLMError:
    """Convierte una respuesta de error del proveedor en excepción de dominio.

    Los problemas de CREDENCIALES o de SALDO (401/402/403) salen con el mismo
    mensaje genérico de "no disponible" a propósito: son fallos de operación de
    Rover, y contarle al usuario que la API key está mal —o que se acabó el
    saldo— no le sirve de nada y sí dice de más sobre la infraestructura. El
    diagnóstico real va al log, en los campos ``provider_*``.
    """
    detalle = _detalle_de_error(body)
    # 5xx y cualquier status no catalogado: el proveedor no respondió algo
    # utilizable, y para el llamador es indistinguible de estar caído.
    por_defecto: tuple[type[LLMError], str] = (
        (LLMUnavailable, _MSG_UNAVAILABLE)
        if status_code >= 500
        else (LLMProviderError, _MSG_INTERNAL)
    )
    excepcion, mensaje = _STATUS_A_DOMINIO.get(status_code, por_defecto)
    return excepcion(
        mensaje,
        provider_status=status_code,
        provider_error_code=detalle[0],
        provider_message=detalle[1],
    )


def _detalle_de_error(body: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """``(código, mensaje)`` del proveedor, para el LOG. Nunca para el cliente."""
    if not isinstance(body, dict):
        return None, None
    error = body.get("error")
    if not isinstance(error, dict):
        return None, None
    codigo = error.get("code") or error.get("type")
    mensaje = error.get("message")
    return (
        str(codigo) if codigo is not None else None,
        str(mensaje) if mensaje is not None else None,
    )


# --- Parseo de respuestas ----------------------------------------------------


def _cuerpo_json(texto: str) -> dict[str, Any] | None:
    """Deserializa un objeto JSON; ``None`` si no lo es (o no es un objeto)."""
    try:
        valor: Any = json.loads(texto)
    except ValueError:
        return None
    return valor if isinstance(valor, dict) else None


def _dato_sse(linea: str) -> str | None:
    """Contenido de una línea ``data:`` del SSE, o ``None`` si no lo es.

    El resto de líneas del protocolo —la vacía que separa eventos, los
    comentarios ``:`` de keep-alive, cabeceras como ``event:``— se ignoran: en
    esta API no llevan información.
    """
    if not linea.startswith("data:"):
        return None
    return linea[len("data:") :].strip()


def _primera_opcion(body: dict[str, Any]) -> dict[str, Any]:
    """``choices[0]`` como objeto, o vacío si no hay (chunk final de usage)."""
    choices = body.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        opcion: dict[str, Any] = choices[0]
        return opcion
    return {}


def _texto(valor: Any) -> str:
    """Normaliza un campo de contenido a texto (``null`` es lo normal en el stream)."""
    return valor if isinstance(valor, str) else ""


def _parse_usage(body: dict[str, Any]) -> Usage | None:
    """Consumo reportado por el proveedor, si lo trae.

    ``prompt_cache_hit_tokens`` es propio de DeepSeek; su ausencia no es un
    error, solo significa que ese proveedor no reporta acierto de caché.
    """
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    return Usage(
        input_tokens=_entero(usage.get("prompt_tokens")),
        output_tokens=_entero(usage.get("completion_tokens")),
        cached_input_tokens=_entero(usage.get("prompt_cache_hit_tokens")),
    )


def _entero(valor: Any) -> int:
    """Entero no negativo, o 0 si el campo falta o no es numérico."""
    return valor if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0 else 0


def _parse_completion(body: dict[str, Any], *, fallback_model: str) -> Completion:
    """Respuesta completa → ``Completion``.

    Un 2xx sin ``choices`` utilizable es una respuesta incoherente, no una
    respuesta vacía: se trata como fallo del proveedor en vez de devolver un
    texto en blanco que el usuario vería como "el asistente no dijo nada".

    Solo se lee ``message.content``. Con el razonamiento activado el proveedor
    añade ahí un ``reasoning_content``, y con non-think —el modo por defecto,
    ver el docstring del módulo— no aparece: el parseo funciona igual en los
    dos casos porque **nunca dependió de ese campo**. Lo que el modelo pensó no
    es la respuesta al usuario, así que tampoco se propaga hacia arriba.
    """
    opcion = _primera_opcion(body)
    mensaje = opcion.get("message")
    if not isinstance(mensaje, dict):
        raise LLMProviderError(_MSG_INTERNAL, provider_message="respuesta sin choices[0].message")

    modelo = body.get("model")
    finish = opcion.get("finish_reason")
    return Completion(
        text=_texto(mensaje.get("content")),
        model=modelo if isinstance(modelo, str) and modelo else fallback_model,
        usage=_parse_usage(body),
        finish_reason=finish if isinstance(finish, str) else None,
    )


def _parse_chunk(evento: dict[str, Any], *, fallback_model: str) -> tuple[CompletionChunk, str]:
    """Evento del stream → ``(chunk, modelo)``.

    Devuelve también el modelo porque el proveedor lo repite en cada evento y
    puede ser MÁS preciso que el configurado (un alias como ``deepseek-chat``
    resuelve a una versión concreta): la instrumentación debe registrar el que
    respondió de verdad.

    Solo se lee ``delta.content``. Con el razonamiento activado, los eventos de
    la fase de pensamiento traen ``delta.reasoning_content`` y ``content`` a
    ``null``: salen como trozos de texto vacío, que es exactamente lo que
    queremos (no se enseña al usuario lo que el modelo está rumiando). Con
    non-think esos eventos ni siquiera existen. Ninguno de los dos caminos
    necesita conocer el campo.
    """
    opcion = _primera_opcion(evento)
    delta = opcion.get("delta")
    finish = opcion.get("finish_reason")
    modelo = evento.get("model")
    return (
        CompletionChunk(
            text=_texto(delta.get("content")) if isinstance(delta, dict) else "",
            finish_reason=finish if isinstance(finish, str) else None,
            usage=_parse_usage(evento),
        ),
        modelo if isinstance(modelo, str) and modelo else fallback_model,
    )


# --- Utilidades de instrumentación -------------------------------------------


def _ms_desde(inicio: float) -> float:
    """Milisegundos transcurridos. ``perf_counter``: monótono, inmune al reloj."""
    return (time.perf_counter() - inicio) * 1000.0


def _context_chars(mensajes: Iterable[dict[str, Any]]) -> int:
    """Tamaño del contexto en caracteres — el sustituto SEGURO del contenido.

    Correlaciona contexto grande con latencia o con fallos sin copiar una sola
    palabra de la conversación a los logs (ver ``instrumentation.py``).
    """
    return sum(len(_texto(m.get("content"))) for m in mensajes)
