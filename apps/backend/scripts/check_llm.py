"""Comprobación manual contra el proveedor REAL (no es un test, no corre en CI).

Con la key de tu ``.env`` hace tres llamadas y enseña la línea de
instrumentación de cada una:

1. un completado normal,
2. **el mismo completado otra vez** — sirve para ver el caché del prefijo
   estable funcionando: la primera lo llena, la segunda debe acertar
   (``cached_input_tokens`` > 0). Es el criterio observable de la HU-2.2,
3. un streaming, para comprobar que los trozos llegan de a poco.

    cd apps/backend
    uv run python -m scripts.check_llm
    uv run python -m scripts.check_llm "¿qué llevo a Cartagena en julio?"

Requiere ``ROVER_LLM_API_KEY`` en ``apps/backend/.env`` (o en el entorno). Los
tests NO usan este script ni la key real: ver ``tests/test_llm.py``.
"""

import asyncio
import sys

from app.core.logging import configure_logging
from app.services.llm import (
    DEFAULT_SYSTEM_PROMPT,
    Completion,
    LLMError,
    Message,
    Role,
    get_llm_provider,
)

PREGUNTA_POR_DEFECTO = "En una frase: ¿qué tal el clima en Bogotá en julio?"


async def main() -> int:
    # Logs en texto y por stdout: aquí lo que interesa es LEER la línea de
    # instrumentación (tokens, latencia, cache hit), no parsearla.
    configure_logging(log_format="text")

    pregunta = sys.argv[1] if len(sys.argv) > 1 else PREGUNTA_POR_DEFECTO
    mensajes = [Message(role=Role.USER, content=pregunta)]

    try:
        proveedor = get_llm_provider()
        print(f"\n→ modelo: {proveedor.model}")
        print(f"→ system prompt: {len(DEFAULT_SYSTEM_PROMPT)} caracteres (prefijo estable)")
        print(f"→ pregunta: {pregunta}\n")

        print("--- 1) completado (sin streaming) ---")
        primera = await proveedor.complete(mensajes)
        print(primera.text)
        print(f"[usage: {primera.usage}]\n")

        print("--- 2) la MISMA llamada otra vez (caché del prefijo estable) ---")
        segunda = await proveedor.complete(mensajes)
        print(f"[usage: {segunda.usage}]")
        _informe_de_cache(segunda)

        print("--- 3) streaming (debe aparecer a trozos) ---")
        async for trozo in proveedor.stream(mensajes):
            print(trozo.text, end="", flush=True)
        print("\n")
    except LLMError as exc:
        # El mensaje es el SEGURO para un usuario; el diagnóstico del proveedor
        # va aparte y aquí sí se enseña, que para eso es una herramienta local.
        print(f"\n✗ {exc}")
        print(
            f"  [proveedor: status={exc.provider_status} "
            f"code={exc.provider_error_code} msg={exc.provider_message}]"
        )
        return 1

    print("✓ el proveedor responde")
    return 0


def _informe_de_cache(segunda: Completion) -> None:
    """Traduce el ``usage`` de la segunda llamada a un veredicto legible.

    Se mira la SEGUNDA y no la primera: la primera es la que LLENA el caché
    (que llegue con aciertos solo significa que alguien mandó el mismo prefijo
    hace poco). Un cero en la segunda es la señal de que algo está invalidando
    el prefijo.
    """
    usage = segunda.usage
    if usage is None:
        print("  ? el proveedor no reportó consumo; no se puede juzgar el caché\n")
        return

    if usage.cached_input_tokens > 0:
        print(
            f"  ✓ caché acertado: {usage.cached_input_tokens}/{usage.input_tokens} "
            f"tokens de entrada servidos de caché ({usage.cache_hit_ratio:.0%})\n"
        )
    else:
        print(
            "  ✗ cached_input_tokens = 0 en la segunda llamada. El prefijo estable NO está\n"
            "    funcionando: algo cambia entre peticiones (¿se interpola algo en el system\n"
            "    prompt?) o el prefijo no llega al bloque mínimo de 64 tokens del proveedor.\n"
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
