"""Instrumentación de cada llamada al LLM (HU-2.1) sobre los logs de la HU-1.12.

## Para qué es esto, más allá de "ver qué pasa"

Es la **semilla del router por dificultad**. Ese router —mandar lo difícil a un
modelo caro y lo fácil al barato— está DIFERIDO a propósito, y su disparador es
justamente esta tabla: se activará cuando estos datos muestren que el modelo
barato falla o exige reintentos en una fracción significativa del tráfico (ver
docs/backlog.md § Diferido → Router por dificultad). Sin ellos, ese router se
diseñaría contra una intuición en vez de contra ejemplos reales.

Por eso la línea se emite **siempre**, con la misma forma y con campos
prefijados ``llm_``: una sola línea por llamada, todas con las mismas claves,
filtrable por ``logger == "app.llm"``. Es lo que hace la diferencia entre unos
logs bonitos y una serie que se puede agregar (percentil de latencia por
modelo, tasa de acierto del caché, tokens por conversación) el día que haya que
decidir con números.

También alimenta, sin trabajo extra, el control de consumo por plan de la
HU-2.8: los tokens de entrada/salida por llamada son la unidad que ahí se
factura.

## Qué se loguea y qué NO

Se registran **metadatos y magnitudes**, nunca contenido:

- ✅ modelo, proveedor, capacidad, si fue streaming, resultado, latencia total,
  latencia hasta el primer trozo, tokens de entrada/salida, tokens servidos de
  caché, motivo de fin, número de mensajes del contexto y tamaño del contexto
  en caracteres.
- ❌ el texto de los mensajes, el system prompt, la respuesta del modelo, la
  API key y la URL con credenciales.

El tamaño en caracteres (``llm_context_chars``) es el sustituto deliberado del
contenido: sirve para correlacionar contexto grande con latencia o con fallos
—que es para lo que se querría mirar el prompt— sin copiar ni una palabra de
una conversación privada a un sistema de logs. Los mensajes de un usuario son
suyos, y un log es el sitio más fácil de exportar por accidente.
"""

import logging
from typing import Literal

from app.services.llm.base import Capability, Usage

#: Logger dedicado: una llamada al LLM es una línea de ``app.llm``, y eso hace
#: que se pueda aislar la serie completa con un solo filtro.
logger = logging.getLogger("app.llm")

#: Cómo terminó la llamada.
#:  - ``ok``        → respuesta completa entregada.
#:  - ``error``     → falló (el tipo va en ``llm_error``).
#:  - ``cancelled`` → el consumidor abandonó el stream a mitad (p. ej. el
#:                    usuario cerró la pestaña). Se separa de ``error`` porque
#:                    NO es un fallo del proveedor, pero sí gastó tokens.
Outcome = Literal["ok", "error", "cancelled"]


def log_llm_call(
    *,
    provider: str,
    model: str,
    capability: Capability,
    streaming: bool,
    outcome: Outcome,
    duration_ms: float,
    time_to_first_chunk_ms: float | None = None,
    usage: Usage | None = None,
    finish_reason: str | None = None,
    message_count: int,
    context_chars: int,
    error: str | None = None,
) -> None:
    """Emite la línea de uso/calidad de UNA llamada al LLM.

    Nivel ``INFO`` en el camino feliz y ``WARNING`` cuando falla: un error
    hablando con el proveedor merece verse sin bajar el nivel de todo el
    logging, pero no es un ``ERROR`` de la aplicación — el 5xx que llegue al
    cliente ya se registra por su cuenta (HU-1.8).

    Los campos van por ``extra=``, así que en producción salen como claves del
    JSON (HU-1.12) y en local caben en una línea legible.
    """
    campos: dict[str, object] = {
        "llm_provider": provider,
        "llm_model": model,
        "llm_capability": capability.value,
        "llm_streaming": streaming,
        "llm_outcome": outcome,
        # Redondeado a la décima de ms: la precisión que sobra solo engorda la
        # línea (y ninguna decisión depende de un microsegundo).
        "llm_duration_ms": round(duration_ms, 1),
        "llm_messages": message_count,
        "llm_context_chars": context_chars,
    }

    if time_to_first_chunk_ms is not None:
        # La métrica que de verdad percibe el usuario en streaming: cuánto
        # tarda en aparecer la primera palabra, no cuánto dura la respuesta.
        campos["llm_ttfc_ms"] = round(time_to_first_chunk_ms, 1)

    if usage is not None:
        campos["llm_input_tokens"] = usage.input_tokens
        campos["llm_output_tokens"] = usage.output_tokens
        campos["llm_cached_input_tokens"] = usage.cached_input_tokens
        campos["llm_cache_hit"] = usage.cache_hit
        campos["llm_cache_hit_ratio"] = round(usage.cache_hit_ratio, 3)

    if finish_reason is not None:
        campos["llm_finish_reason"] = finish_reason

    if error is not None:
        # El TIPO de la excepción de dominio, no su mensaje: es un valor
        # cerrado y agregable ("cuántos LLMUnavailable esta hora").
        campos["llm_error"] = error

    nivel = logging.WARNING if outcome == "error" else logging.INFO
    logger.log(
        nivel,
        "llamada al LLM %s → %s (%.1f ms)",
        model,
        outcome,
        duration_ms,
        extra=campos,
    )
