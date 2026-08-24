"""Tests de la capa de proveedor de LLM (HU-2.1). NUNCA llaman a DeepSeek.

El proveedor está simulado a dos niveles distintos, y cada uno prueba algo que
el otro no puede:

1. **``httpx.MockTransport``** (la mayoría de los tests): se ejerce el camino
   REAL de ``DeepSeekProvider`` —cuerpo de la petición, cabeceras, parseo del
   JSON, parseo del SSE, traducción de errores, instrumentación— contra
   respuestas escritas a mano con la forma que devuelve la API. Un mock del
   método ``complete`` no probaría nada de eso: pasaría igual aunque el cliente
   mandara el cuerpo al revés.
2. **Un doble que implementa el ``Protocol``** (``_ProveedorDeMentira``): prueba
   que el contrato es implementable por CUALQUIERA sin heredar de nada, que es
   la promesa de la interfaz, y que el registro lo acepta como sustituto.

El CI no tiene la key: ninguna prueba la necesita, y hay un test que lo vigila
(``test_ninguna_llamada_sale_a_la_red``).
"""

import io
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Sequence
from contextlib import aclosing
from typing import Any

import httpx
import pytest
from anyio.abc import BlockingPortal

from app.core.logging import configure_logging
from app.services.llm import (
    DEFAULT_SYSTEM_PROMPT,
    Capability,
    Completion,
    CompletionChunk,
    LLMAuthError,
    LLMBadRequest,
    LLMCapabilityUnavailable,
    LLMNotConfigured,
    LLMProvider,
    LLMProviderError,
    LLMQuotaExceeded,
    LLMRateLimited,
    LLMUnavailable,
    Message,
    Role,
    ToolCall,
    ToolCallAccumulator,
    ToolCallDelta,
    ToolSpec,
    Usage,
    get_llm_provider,
    set_llm_provider,
)
from app.services.llm.deepseek import DeepSeekProvider, ThinkingMode

API_KEY = "clave-de-mentira-que-no-debe-aparecer-en-ningun-log"
MENSAJES = [Message(role=Role.USER, content="¿qué tal el clima en Bogotá?")]


# --- Utilidades --------------------------------------------------------------


def _respuesta_completa(
    *,
    texto: str = "Está nublado.",
    model: str = "deepseek-v4-flash",
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Cuerpo con la forma de un 200 no-streaming de la API."""
    return {
        "id": "chatcmpl-1",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": texto},
                "finish_reason": "stop",
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 42,
            "completion_tokens": 7,
            "total_tokens": 49,
            "prompt_cache_hit_tokens": 32,
            "prompt_cache_miss_tokens": 10,
        },
    }


def _evento_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _stream_de_ejemplo(trozos: Sequence[str]) -> str:
    """Stream SSE con la forma real: deltas, chunk de usage y ``[DONE]``."""
    lineas = [
        _evento_sse(
            {
                "model": "deepseek-v4-flash",
                "choices": [{"index": 0, "delta": {"content": trozo}, "finish_reason": None}],
            }
        )
        for trozo in trozos
    ]
    # Penúltimo evento: sin texto, con el motivo de fin.
    lineas.append(
        _evento_sse(
            {
                "model": "deepseek-v4-flash",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        )
    )
    # Último: el consumo (llega porque pedimos stream_options.include_usage).
    lineas.append(
        _evento_sse(
            {
                "model": "deepseek-v4-flash",
                "choices": [],
                "usage": {
                    "prompt_tokens": 42,
                    "completion_tokens": 3,
                    "prompt_cache_hit_tokens": 0,
                },
            }
        )
    )
    lineas.append("data: [DONE]\n\n")
    return "".join(lineas)


class Espia:
    """Guarda la petición que recibió el transporte simulado."""

    def __init__(self) -> None:
        self.peticion: httpx.Request | None = None

    @property
    def cuerpo(self) -> dict[str, Any]:
        assert self.peticion is not None, "no se registró ninguna petición"
        body: dict[str, Any] = json.loads(self.peticion.content)
        return body


def _proveedor(
    handler: Any,
    *,
    model: str = "deepseek-v4-flash",
    thinking: ThinkingMode = "disabled",
) -> tuple[DeepSeekProvider, Espia]:
    """Proveedor real enchufado a un transporte simulado.

    El default de ``thinking`` es el mismo que el de producción a propósito: si
    algún día cambia el default de verdad, estos tests hablan del modo en que
    corre el producto y no de uno inventado para el test.
    """
    espia = Espia()

    def envolver(request: httpx.Request) -> httpx.Response:
        espia.peticion = request
        respuesta: httpx.Response = handler(request)
        return respuesta

    proveedor = DeepSeekProvider(
        api_key=API_KEY,
        base_url="https://api.deepseek.com",
        model=model,
        temperature=0.7,
        max_output_tokens=2048,
        timeout_seconds=5.0,
        thinking=thinking,
        transport=httpx.MockTransport(envolver),
    )
    return proveedor, espia


def _json_handler(body: dict[str, Any], status_code: int = 200) -> Any:
    return lambda request: httpx.Response(status_code, json=body)


def _sse_handler(texto: str, status_code: int = 200) -> Any:
    return lambda request: httpx.Response(
        status_code, text=texto, headers={"Content-Type": "text/event-stream"}
    )


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    """Captura los logs en JSON para poder afirmar sobre los campos emitidos."""
    buffer = io.StringIO()
    configure_logging(stream=buffer, log_format="json")
    try:
        yield buffer
    finally:
        configure_logging()


def _lineas_llm(buffer: io.StringIO) -> list[dict[str, Any]]:
    lineas = [json.loads(linea) for linea in buffer.getvalue().splitlines() if linea.strip()]
    return [linea for linea in lineas if linea["logger"] == "app.llm"]


# --- Completado NO streaming -------------------------------------------------


def test_completado_devuelve_la_respuesta_del_modelo(loop_de_test: BlockingPortal) -> None:
    proveedor, _ = _proveedor(_json_handler(_respuesta_completa(texto="Está nublado.")))

    respuesta = loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert respuesta.text == "Está nublado."
    assert respuesta.model == "deepseek-v4-flash"
    assert respuesta.finish_reason == "stop"
    assert respuesta.usage == Usage(input_tokens=42, output_tokens=7, cached_input_tokens=32)


def test_la_peticion_va_al_endpoint_y_con_la_key_en_la_cabecera(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    peticion = espia.peticion
    assert peticion is not None
    assert str(peticion.url) == "https://api.deepseek.com/chat/completions"
    assert peticion.headers["Authorization"] == f"Bearer {API_KEY}"


def test_el_modelo_y_los_parametros_salen_de_la_configuracion(
    loop_de_test: BlockingPortal,
) -> None:
    """Nada hardcodeado: lo que se manda es lo que se le pasó al proveedor."""
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()), model="otro-modelo")

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert espia.cuerpo["model"] == "otro-modelo"
    assert espia.cuerpo["temperature"] == 0.7
    assert espia.cuerpo["max_tokens"] == 2048
    assert espia.cuerpo["stream"] is False


def test_los_parametros_de_generacion_se_pueden_sobrescribir_por_llamada(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES, temperature=0.0, max_output_tokens=64))

    assert espia.cuerpo["temperature"] == 0.0
    assert espia.cuerpo["max_tokens"] == 64


# --- Prefijo estable (system prompt) -----------------------------------------


def test_el_system_prompt_va_siempre_primero(loop_de_test: BlockingPortal) -> None:
    """Es la condición para que el caché automático del proveedor muerda."""
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(
        lambda: proveedor.complete(
            [
                Message(role=Role.USER, content="hola"),
                Message(role=Role.ASSISTANT, content="¿qué tal?"),
                Message(role=Role.USER, content="bien"),
            ],
            system_prompt="Eres Rover.",
        )
    )

    mensajes = espia.cuerpo["messages"]
    assert mensajes[0] == {"role": "system", "content": "Eres Rover."}
    assert [m["role"] for m in mensajes] == ["system", "user", "assistant", "user"]


def test_sin_system_prompt_explicito_se_usa_el_del_repo(loop_de_test: BlockingPortal) -> None:
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert espia.cuerpo["messages"][0]["content"] == DEFAULT_SYSTEM_PROMPT


def test_el_stream_tambien_manda_el_prompt_del_repo(loop_de_test: BlockingPortal) -> None:
    """El camino normal del producto es el streaming: si aquí faltara el prompt,
    Rover tendría personalidad solo en las llamadas que casi nadie hace."""
    proveedor, espia = _proveedor(_sse_handler(_stream_de_ejemplo(["hola"])))

    async def consumir() -> None:
        async for _ in proveedor.stream(MENSAJES):
            pass

    loop_de_test.call(consumir)

    assert espia.cuerpo["messages"][0] == {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}


def test_el_prefijo_es_identico_entre_llamadas(loop_de_test: BlockingPortal) -> None:
    """Si variara (una fecha interpolada, p. ej.) el caché no acertaría nunca."""
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete([Message(role=Role.USER, content="una")]))
    primero = espia.cuerpo["messages"][0]
    loop_de_test.call(lambda: proveedor.complete([Message(role=Role.USER, content="otra")]))
    segundo = espia.cuerpo["messages"][0]

    assert primero == segundo


# --- Modo de razonamiento (non-think) ----------------------------------------


def test_el_razonamiento_va_desactivado_por_defecto(loop_de_test: BlockingPortal) -> None:
    """DeepSeek V4 razona por defecto y lo cobra como salida.

    Medido contra el proveedor real: ~1.163 tokens de salida y ~15 s para una
    respuesta conversacional de cuatro frases. El chat de Rover va en non-think.
    """
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert espia.cuerpo["thinking"] == {"type": "disabled"}


def test_el_stream_tambien_va_en_non_think(loop_de_test: BlockingPortal) -> None:
    """El streaming es el camino normal del producto: si el ahorro no llegara
    aquí, no llegaría a casi ninguna petición real."""
    proveedor, espia = _proveedor(_sse_handler(_stream_de_ejemplo(["hola"])))

    async def consumir() -> None:
        async for _ in proveedor.stream(MENSAJES):
            pass

    loop_de_test.call(consumir)

    assert espia.cuerpo["thinking"] == {"type": "disabled"}


def test_el_razonamiento_se_puede_reactivar_por_configuracion(
    loop_de_test: BlockingPortal,
) -> None:
    """Es config y no una constante porque el router por dificultad (diferido)
    querrá lo contrario para lo que sí lo vale: un itinerario multi-ciudad."""
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()), thinking="enabled")

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert espia.cuerpo["thinking"] == {"type": "enabled"}


def test_con_provider_default_el_campo_no_viaja(loop_de_test: BlockingPortal) -> None:
    """``thinking`` es una extensión propietaria de DeepSeek: un proveedor
    OpenAI-compatible que rechace parámetros desconocidos se atiende cambiando
    entorno, no editando ``deepseek.py``."""
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()), thinking="provider_default")

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert "thinking" not in espia.cuerpo


def test_la_respuesta_se_parsea_sin_reasoning_content(loop_de_test: BlockingPortal) -> None:
    """En non-think ese campo NO llega. El parseo nunca dependió de él."""
    cuerpo = {
        "id": "chatcmpl-1",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Lleva chaqueta."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 656, "completion_tokens": 12},
    }
    proveedor, _ = _proveedor(_json_handler(cuerpo))

    respuesta = loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert respuesta.text == "Lleva chaqueta."
    assert respuesta.usage == Usage(input_tokens=656, output_tokens=12)


def test_si_llegara_reasoning_content_no_se_cuela_en_la_respuesta(
    loop_de_test: BlockingPortal,
) -> None:
    """Reactivar ``thinking`` no debe cambiar lo que ve el usuario: lo que el
    modelo rumia no es la respuesta."""
    cuerpo = _respuesta_completa(texto="Lleva chaqueta.")
    cuerpo["choices"][0]["message"]["reasoning_content"] = "Bogotá está a 2.600 m, así que…"
    proveedor, _ = _proveedor(_json_handler(cuerpo), thinking="enabled")

    respuesta = loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert respuesta.text == "Lleva chaqueta."


def test_el_stream_no_enseña_el_razonamiento(loop_de_test: BlockingPortal) -> None:
    """Con ``thinking`` activo, los eventos de la fase de pensamiento traen
    ``reasoning_content`` y ``content`` a ``null``: salen como texto vacío y no
    tumban el stream."""
    cuerpo = (
        _evento_sse(
            {
                "model": "m",
                "choices": [{"index": 0, "delta": {"reasoning_content": "pensando…"}}],
            }
        )
        + _evento_sse({"model": "m", "choices": [{"index": 0, "delta": {"content": "Lleva"}}]})
        + _evento_sse({"model": "m", "choices": [{"index": 0, "delta": {"content": " chaqueta."}}]})
        + "data: [DONE]\n\n"
    )
    proveedor, _ = _proveedor(_sse_handler(cuerpo), thinking="enabled")

    async def recolectar() -> str:
        return "".join([trozo.text async for trozo in proveedor.stream(MENSAJES)])

    assert loop_de_test.call(recolectar) == "Lleva chaqueta."


# --- Streaming ---------------------------------------------------------------


def test_el_stream_emite_los_trozos_en_orden(loop_de_test: BlockingPortal) -> None:
    proveedor, _ = _proveedor(_sse_handler(_stream_de_ejemplo(["Hola", ", ", "viajero"])))

    async def recolectar() -> list[str]:
        return [trozo.text async for trozo in proveedor.stream(MENSAJES) if trozo.text]

    assert loop_de_test.call(recolectar) == ["Hola", ", ", "viajero"]


def test_concatenar_los_trozos_reconstruye_la_respuesta(loop_de_test: BlockingPortal) -> None:
    """El contrato del stream: los ``text`` son deltas, no acumulados."""
    proveedor, _ = _proveedor(_sse_handler(_stream_de_ejemplo(["Va", " a ", "llover"])))

    async def recolectar() -> str:
        return "".join([trozo.text async for trozo in proveedor.stream(MENSAJES)])

    assert loop_de_test.call(recolectar) == "Va a llover"


def test_el_stream_pide_el_consumo_y_lo_entrega_en_el_ultimo_trozo(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor, espia = _proveedor(_sse_handler(_stream_de_ejemplo(["hola"])))

    async def recolectar() -> list[CompletionChunk]:
        return [trozo async for trozo in proveedor.stream(MENSAJES)]

    trozos = loop_de_test.call(recolectar)

    assert espia.cuerpo["stream"] is True
    assert espia.cuerpo["stream_options"] == {"include_usage": True}
    assert trozos[-1].usage == Usage(input_tokens=42, output_tokens=3, cached_input_tokens=0)
    assert any(trozo.finish_reason == "stop" for trozo in trozos)


def test_el_stream_ignora_las_lineas_que_no_son_datos(loop_de_test: BlockingPortal) -> None:
    """Keep-alives y líneas en blanco no deben aparecer como texto."""
    cuerpo = (
        ": keep-alive\n\n"
        + _evento_sse({"model": "m", "choices": [{"delta": {"content": "solo esto"}, "index": 0}]})
        + "\n"
        + "data: [DONE]\n\n"
    )
    proveedor, _ = _proveedor(_sse_handler(cuerpo))

    async def recolectar() -> list[str]:
        return [trozo.text async for trozo in proveedor.stream(MENSAJES)]

    assert loop_de_test.call(recolectar) == ["solo esto"]


def test_un_evento_ilegible_no_tumba_el_stream(loop_de_test: BlockingPortal) -> None:
    """Una respuesta a medias en pantalla vale más que un corte por un evento roto."""
    cuerpo = (
        _evento_sse({"model": "m", "choices": [{"delta": {"content": "antes"}, "index": 0}]})
        + "data: {esto no es json}\n\n"
        + _evento_sse({"model": "m", "choices": [{"delta": {"content": " y después"}, "index": 0}]})
        + "data: [DONE]\n\n"
    )
    proveedor, _ = _proveedor(_sse_handler(cuerpo))

    async def recolectar() -> str:
        return "".join([trozo.text async for trozo in proveedor.stream(MENSAJES)])

    assert loop_de_test.call(recolectar) == "antes y después"


# --- Traducción de errores ---------------------------------------------------


@pytest.mark.parametrize(
    ("status", "excepcion"),
    [
        (400, LLMBadRequest),
        (401, LLMAuthError),
        (402, LLMQuotaExceeded),
        (403, LLMAuthError),
        (422, LLMBadRequest),
        (429, LLMRateLimited),
        (500, LLMUnavailable),
        (503, LLMUnavailable),
        (418, LLMProviderError),
    ],
)
def test_un_error_del_proveedor_se_traduce_a_dominio(
    loop_de_test: BlockingPortal, status: int, excepcion: type[Exception]
) -> None:
    cuerpo = {"error": {"message": "algo pasó", "type": "server_error", "code": "invalid_request"}}
    proveedor, _ = _proveedor(_json_handler(cuerpo, status_code=status))

    with pytest.raises(excepcion):
        loop_de_test.call(lambda: proveedor.complete(MENSAJES))


def test_el_error_traducido_guarda_el_diagnostico_solo_para_el_log(
    loop_de_test: BlockingPortal,
) -> None:
    cuerpo = {"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}}
    proveedor, _ = _proveedor(_json_handler(cuerpo, status_code=429))

    with pytest.raises(LLMRateLimited) as excinfo:
        loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    # El mensaje que vería un usuario no repite el del proveedor…
    assert "Rate limit reached" not in str(excinfo.value)
    # …pero el diagnóstico está disponible para el servidor.
    assert excinfo.value.provider_status == 429
    assert excinfo.value.provider_error_code == "rate_limit_exceeded"
    assert excinfo.value.provider_message == "Rate limit reached"


def test_la_red_caida_es_un_proveedor_no_disponible(loop_de_test: BlockingPortal) -> None:
    def revienta(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin ruta al host")

    proveedor, _ = _proveedor(revienta)

    with pytest.raises(LLMUnavailable):
        loop_de_test.call(lambda: proveedor.complete(MENSAJES))


def test_un_timeout_es_un_proveedor_no_disponible(loop_de_test: BlockingPortal) -> None:
    def revienta(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("tardó demasiado")

    proveedor, _ = _proveedor(revienta)

    with pytest.raises(LLMUnavailable):
        loop_de_test.call(lambda: proveedor.complete(MENSAJES))


def test_una_respuesta_con_forma_inesperada_no_se_devuelve_como_vacia(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor, _ = _proveedor(_json_handler({"choices": []}))

    with pytest.raises(LLMProviderError):
        loop_de_test.call(lambda: proveedor.complete(MENSAJES))


def test_un_error_antes_del_stream_tambien_se_traduce(loop_de_test: BlockingPortal) -> None:
    """El rechazo llega con status, antes del primer trozo."""
    proveedor, _ = _proveedor(
        _sse_handler(json.dumps({"error": {"message": "no", "code": "x"}}), status_code=429)
    )

    async def consumir() -> list[str]:
        return [trozo.text async for trozo in proveedor.stream(MENSAJES)]

    with pytest.raises(LLMRateLimited):
        loop_de_test.call(consumir)


def test_un_corte_a_mitad_del_stream_se_traduce(loop_de_test: BlockingPortal) -> None:
    """El fallo puede llegar cuando el usuario ya está viendo texto."""

    def a_medias(request: httpx.Request) -> httpx.Response:
        async def contenido() -> AsyncIterator[bytes]:
            yield _evento_sse(
                {"model": "m", "choices": [{"delta": {"content": "empieza"}, "index": 0}]}
            ).encode()
            raise httpx.ReadError("la conexión se cayó")

        return httpx.Response(200, content=contenido())

    proveedor, _ = _proveedor(a_medias)

    async def consumir() -> list[str]:
        return [trozo.text async for trozo in proveedor.stream(MENSAJES)]

    with pytest.raises(LLMUnavailable):
        loop_de_test.call(consumir)


# --- Instrumentación ---------------------------------------------------------


def test_se_registra_el_uso_de_una_llamada_completa(
    loop_de_test: BlockingPortal, logs: io.StringIO
) -> None:
    proveedor, _ = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    (linea,) = _lineas_llm(logs)
    assert linea["llm_provider"] == "deepseek"
    assert linea["llm_model"] == "deepseek-v4-flash"
    assert linea["llm_outcome"] == "ok"
    assert linea["llm_streaming"] is False
    assert linea["llm_input_tokens"] == 42
    assert linea["llm_output_tokens"] == 7
    assert linea["llm_cached_input_tokens"] == 32
    assert linea["llm_cache_hit"] is True
    assert linea["llm_finish_reason"] == "stop"
    assert isinstance(linea["llm_duration_ms"], (int, float))
    assert linea["llm_capability"] == "text"


def test_se_registra_el_uso_de_un_stream_con_latencia_del_primer_trozo(
    loop_de_test: BlockingPortal, logs: io.StringIO
) -> None:
    proveedor, _ = _proveedor(_sse_handler(_stream_de_ejemplo(["uno", "dos"])))

    async def consumir() -> None:
        async for _ in proveedor.stream(MENSAJES):
            pass

    loop_de_test.call(consumir)

    (linea,) = _lineas_llm(logs)
    assert linea["llm_streaming"] is True
    assert linea["llm_outcome"] == "ok"
    assert linea["llm_input_tokens"] == 42
    assert linea["llm_output_tokens"] == 3
    assert linea["llm_cache_hit"] is False
    # La métrica que percibe el usuario: cuánto tarda en aparecer lo primero.
    assert isinstance(linea["llm_ttfc_ms"], (int, float))


def test_un_fallo_tambien_queda_instrumentado(
    loop_de_test: BlockingPortal, logs: io.StringIO
) -> None:
    proveedor, _ = _proveedor(_json_handler({"error": {"message": "x"}}, status_code=429))

    with pytest.raises(LLMRateLimited):
        loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    (linea,) = _lineas_llm(logs)
    assert linea["llm_outcome"] == "error"
    assert linea["llm_error"] == "LLMRateLimited"
    assert linea["level"] == "WARNING"


def test_abandonar_el_stream_se_registra_como_cancelado(
    loop_de_test: BlockingPortal, logs: io.StringIO
) -> None:
    """No es un fallo del proveedor, pero los tokens ya se gastaron."""
    proveedor, _ = _proveedor(_sse_handler(_stream_de_ejemplo(["uno", "dos", "tres"])))

    async def consumir_solo_el_primero() -> None:
        # ``aclosing`` cierra el generador AQUÍ y no cuando pase el recolector:
        # es lo que hará el endpoint SSE de la HU-2.4 cuando el cliente se vaya,
        # y sin él este test dependería del momento del GC.
        async with aclosing(proveedor.stream(MENSAJES)) as trozos:
            async for _ in trozos:
                break

    loop_de_test.call(consumir_solo_el_primero)

    (linea,) = _lineas_llm(logs)
    assert linea["llm_outcome"] == "cancelled"


def test_la_instrumentacion_no_filtra_secretos_ni_contenido(
    loop_de_test: BlockingPortal, logs: io.StringIO
) -> None:
    """Ni la key, ni el prompt, ni lo que escribió el usuario, ni la respuesta."""
    secreto_del_usuario = "mi itinerario privado a Cartagena"
    proveedor, _ = _proveedor(_json_handler(_respuesta_completa(texto="respuesta del modelo")))

    loop_de_test.call(
        lambda: proveedor.complete([Message(role=Role.USER, content=secreto_del_usuario)])
    )

    salida = logs.getvalue()
    assert API_KEY not in salida
    assert secreto_del_usuario not in salida
    assert "respuesta del modelo" not in salida
    assert DEFAULT_SYSTEM_PROMPT not in salida
    # Lo que SÍ se registra del contexto: cuánto ocupa, no qué dice.
    (linea,) = _lineas_llm(logs)
    assert linea["llm_messages"] == 2  # system + user
    assert linea["llm_context_chars"] == len(DEFAULT_SYSTEM_PROMPT) + len(secreto_del_usuario)


def test_las_lineas_del_llm_se_correlacionan_por_logger(
    loop_de_test: BlockingPortal, logs: io.StringIO
) -> None:
    """Una llamada = una línea de ``app.llm``: la serie es agregable."""
    proveedor, _ = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))
    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert len(_lineas_llm(logs)) == 2


# --- Contrato de la interfaz y registro por capacidad ------------------------


class _ProveedorDeMentira:
    """Implementa el ``Protocol`` sin heredar de nada: esa es la promesa.

    Es también el doble que usarán las HU siguientes (endpoint SSE, agente)
    para no depender de una API externa en sus tests.
    """

    def __init__(self, trozos: Sequence[str]) -> None:
        self._trozos = list(trozos)
        self.recibido: list[Message] = []

    @property
    def model(self) -> str:
        return "modelo-de-mentira"

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.TEXT})

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> Completion:
        self.recibido = list(messages)
        return Completion(text="".join(self._trozos), model=self.model)

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncGenerator[CompletionChunk]:
        self.recibido = list(messages)
        for trozo in self._trozos:
            yield CompletionChunk(text=trozo)


def test_el_proveedor_real_cumple_la_interfaz() -> None:
    """Verificación estructural: si dejara de cumplirla, mypy fallaría aquí."""
    proveedor, _ = _proveedor(_json_handler(_respuesta_completa()))
    conforme: LLMProvider = proveedor

    assert conforme.model == "deepseek-v4-flash"
    assert Capability.TEXT in conforme.capabilities


def test_un_doble_puede_sustituir_al_proveedor(loop_de_test: BlockingPortal) -> None:
    doble: LLMProvider = _ProveedorDeMentira(["listo"])
    set_llm_provider(doble)

    assert get_llm_provider() is doble
    assert loop_de_test.call(lambda: get_llm_provider().complete(MENSAJES)).text == "listo"


def test_una_capacidad_sin_proveedor_falla_claro() -> None:
    """Mejor un error explícito que mandarle una imagen a un modelo de texto."""
    with pytest.raises(LLMCapabilityUnavailable):
        get_llm_provider(Capability.VISION)


def test_el_registro_devuelve_el_de_texto_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_api_key", SecretStr("k"))
    proveedor = get_llm_provider()

    assert proveedor.model == settings.llm_model
    assert Capability.TEXT in proveedor.capabilities
    # Se construye una sola vez por proceso.
    assert get_llm_provider() is proveedor


def test_sin_key_configurada_el_registro_lo_dice_claro(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_api_key", None)

    with pytest.raises(LLMNotConfigured) as excinfo:
        get_llm_provider()

    assert "ROVER_LLM_API_KEY" in str(excinfo.value)


def test_el_registro_enruta_por_capacidad(loop_de_test: BlockingPortal) -> None:
    """El seam: dos capacidades, dos proveedores, el llamador no cambia."""
    texto: LLMProvider = _ProveedorDeMentira(["soy el de texto"])
    vision: LLMProvider = _ProveedorDeMentira(["soy el de visión"])
    set_llm_provider(texto)
    set_llm_provider(vision, capability=Capability.VISION)

    assert get_llm_provider(Capability.TEXT) is texto
    assert get_llm_provider(Capability.VISION) is vision


def test_ninguna_llamada_sale_a_la_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guardia del CI: sin key y sin red, la suite debe seguir pasando.

    Si algún test futuro construyera un proveedor sin transporte simulado, este
    ``AsyncClient`` saboteado lo delataría al intentar abrirse.
    """

    def prohibido(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("un test intentó hablar con el proveedor real")

    monkeypatch.setattr(httpx.AsyncClient, "send", prohibido)
    proveedor, _ = _proveedor(_json_handler(_respuesta_completa()))

    # El transporte simulado no pasa por ``send``: el camino de test está limpio.
    assert proveedor.model == "deepseek-v4-flash"


# --- Tipos de dominio --------------------------------------------------------


def test_el_uso_calcula_el_acierto_de_cache() -> None:
    """La señal de si el prefijo estable está funcionando."""
    assert Usage(input_tokens=100, output_tokens=10, cached_input_tokens=80).cache_hit is True
    assert Usage(input_tokens=100, output_tokens=10, cached_input_tokens=80).cache_hit_ratio == 0.8
    sin_cache = Usage(input_tokens=100, output_tokens=10)
    assert sin_cache.cache_hit is False
    assert sin_cache.cache_hit_ratio == 0.0
    # Sin entrada contabilizada no se divide por cero.
    assert Usage(input_tokens=0, output_tokens=0).cache_hit_ratio == 0.0


def test_los_mensajes_son_inmutables() -> None:
    """El contexto se arma y se manda; parchearlo a mitad sería un bug mudo."""
    mensaje = Message(role=Role.USER, content="hola")

    with pytest.raises(AttributeError):
        mensaje.content = "otra cosa"  # type: ignore[misc]


def test_los_roles_son_los_del_dominio() -> None:
    assert [rol.value for rol in Role] == ["system", "user", "assistant", "tool"]


def test_el_logger_del_llm_no_emite_nada_al_importar(caplog: pytest.LogCaptureFixture) -> None:
    """Importar la capa no debe tocar config ni red (arranque perezoso)."""
    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        import app.services.llm as capa

        assert capa.get_llm_provider is get_llm_provider
    assert caplog.records == []


# --- Tool-calling en la capa de LLM (HU-2.6) ---------------------------------


TOOL_DEL_CLIMA = ToolSpec(
    name="get_weather",
    description="Consulta el clima actual de un lugar.",
    parameters={
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
    },
)


def test_sin_tools_el_cuerpo_no_lleva_la_clave(loop_de_test: BlockingPortal) -> None:
    """Una llamada sin herramientas es byte a byte la de antes de la HU-2.6.

    Importa para el caché: si la clave apareciera vacía, el prefijo de TODAS
    las peticiones cambiaría el día que se añadió el tool-calling.
    """
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES))

    assert "tools" not in espia.cuerpo


def test_las_tools_viajan_en_el_formato_OpenAI(loop_de_test: BlockingPortal) -> None:
    """El envoltorio ``{"type": "function", ...}`` es ruido del proveedor y se queda aquí."""
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES, tools=[TOOL_DEL_CLIMA]))

    assert espia.cuerpo["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Consulta el clima actual de un lugar.",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            },
        }
    ]


def test_el_orden_del_prefijo_estable_no_cambia_con_tools(
    loop_de_test: BlockingPortal,
) -> None:
    """El system prompt sigue primero y las tools van en su propia clave."""
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))

    loop_de_test.call(lambda: proveedor.complete(MENSAJES, tools=[TOOL_DEL_CLIMA]))

    cuerpo = espia.cuerpo
    assert cuerpo["messages"][0]["role"] == "system"
    assert cuerpo["messages"][0]["content"] == DEFAULT_SYSTEM_PROMPT
    # Las definiciones NO son un mensaje más: van fuera de la lista.
    assert all("tool" not in m["role"] for m in cuerpo["messages"])


def test_el_multiturno_con_tools_viaja_completo(loop_de_test: BlockingPortal) -> None:
    """Los tres tipos de mensaje del ida y vuelta, con el ``tool_call_id``.

    Sin ese id el proveedor no sabe a qué petición responde el resultado y
    devuelve 400 — y con varias herramientas a la vez es lo único que las
    distingue.
    """
    proveedor, espia = _proveedor(_json_handler(_respuesta_completa()))
    peticion = ToolCall(id="call_abc", name="get_weather", arguments='{"location":"Bogotá"}')
    contexto = [
        Message(role=Role.USER, content="¿qué tal el clima?"),
        Message(role=Role.ASSISTANT, content="", tool_calls=(peticion,)),
        Message(role=Role.TOOL, content='{"temperature_c": 14.2}', tool_call_id="call_abc"),
    ]

    loop_de_test.call(lambda: proveedor.complete(contexto))

    _, usuario, asistente, resultado = espia.cuerpo["messages"]
    assert usuario == {"role": "user", "content": "¿qué tal el clima?"}
    assert asistente == {
        "role": "assistant",
        # ``content`` va como cadena vacía y NO se omite: algunos proveedores
        # OpenAI-compatibles rechazan el mensaje sin la clave.
        "content": "",
        "tool_calls": [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location":"Bogotá"}'},
            }
        ],
    }
    assert resultado == {
        "role": "tool",
        "content": '{"temperature_c": 14.2}',
        "tool_call_id": "call_abc",
    }


def test_una_respuesta_con_tool_calls_se_parsea_a_dominio(
    loop_de_test: BlockingPortal,
) -> None:
    cuerpo = {
        "id": "chatcmpl-1",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_0",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location":"Bogotá"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    proveedor, _ = _proveedor(_json_handler(cuerpo))

    completion = loop_de_test.call(lambda: proveedor.complete(MENSAJES, tools=[TOOL_DEL_CLIMA]))

    assert completion.text == ""
    assert completion.finish_reason == "tool_calls"
    (llamada,) = completion.tool_calls
    assert llamada.id == "call_0"
    assert llamada.name == "get_weather"
    # Los argumentos van CRUDOS: el parseo es de quien ejecuta, que es quien
    # puede decidir qué hacer si el modelo mandó JSON roto.
    assert llamada.arguments == '{"location":"Bogotá"}'


def test_una_peticion_sin_nombre_se_descarta(loop_de_test: BlockingPortal) -> None:
    """No se puede ni ejecutar ni reportar como fallida: colarla es peor."""
    cuerpo = {
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_0", "function": {"arguments": "{}"}}],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    proveedor, _ = _proveedor(_json_handler(cuerpo))

    assert loop_de_test.call(lambda: proveedor.complete(MENSAJES)).tool_calls == ()


def test_el_stream_reconstruye_una_peticion_partida_en_fragmentos(
    loop_de_test: BlockingPortal,
) -> None:
    """El caso real: el nombre llega en un evento y los argumentos a pedazos."""
    sse = "".join(
        [
            _evento_sse(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_0",
                                        "type": "function",
                                        "function": {"name": "get_weather", "arguments": ""},
                                    }
                                ]
                            },
                        }
                    ],
                }
            ),
            *[
                _evento_sse(
                    {
                        "model": "deepseek-v4-flash",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [{"index": 0, "function": {"arguments": pedazo}}]
                                },
                            }
                        ],
                    }
                )
                for pedazo in ['{"loc', 'ation"', ':"Bogo', 'tá"}']
            ],
            _evento_sse(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                }
            ),
            "data: [DONE]\n\n",
        ]
    )
    proveedor, _ = _proveedor(_sse_handler(sse))

    async def leer() -> tuple[str, tuple[ToolCall, ...]]:
        acumulador = ToolCallAccumulator()
        texto = ""
        async with aclosing(proveedor.stream(MENSAJES, tools=[TOOL_DEL_CLIMA])) as stream:
            async for trozo in stream:
                texto += trozo.text
                for fragmento in trozo.tool_calls:
                    acumulador.add(fragmento)
        return texto, acumulador.result()

    texto, llamadas = loop_de_test.call(leer)

    # El stream es "mudo": todo el turno vino sin una palabra de texto.
    assert texto == ""
    (llamada,) = llamadas
    assert llamada.name == "get_weather"
    assert llamada.arguments == '{"location":"Bogotá"}'


def test_el_acumulador_distingue_varias_peticiones_por_su_indice() -> None:
    acumulador = ToolCallAccumulator()
    acumulador.add(ToolCallDelta(index=1, id="call_1", name="otra"))
    acumulador.add(ToolCallDelta(index=0, id="call_0", name="una"))
    acumulador.add(ToolCallDelta(index=0, arguments='{"a":'))
    acumulador.add(ToolCallDelta(index=1, arguments='{"b":2}'))
    acumulador.add(ToolCallDelta(index=0, arguments="1}"))

    # Ordenadas por índice, no por orden de llegada.
    assert [(c.id, c.name, c.arguments) for c in acumulador.result()] == [
        ("call_0", "una", '{"a":1}'),
        ("call_1", "otra", '{"b":2}'),
    ]


def test_el_acumulador_descarta_lo_que_llego_sin_nombre() -> None:
    """Un fragmento suelto de un stream cortado no es una petición."""
    acumulador = ToolCallAccumulator()
    acumulador.add(ToolCallDelta(index=0, arguments='{"a":1}'))

    assert bool(acumulador) is True
    assert acumulador.result() == ()


def test_el_acumulador_sintetiza_un_id_si_el_proveedor_no_lo_manda() -> None:
    """Raro, pero sin id el resultado no tendría con qué correlacionarse."""
    acumulador = ToolCallAccumulator()
    acumulador.add(ToolCallDelta(index=3, name="una", arguments="{}"))

    (llamada,) = acumulador.result()
    assert llamada.id == "call_3"
