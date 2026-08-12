"""Comprobación manual contra el proveedor REAL (no es un test, no corre en CI).

Hace una llamada completa y otra en streaming con la key de tu ``.env``, y
enseña la línea de instrumentación de cada una. Sirve para verificar de una vez
que la key, la URL base y el modelo son correctos y que el streaming llega
trozo a trozo de verdad.

    cd apps/backend
    uv run python -m scripts.check_llm
    uv run python -m scripts.check_llm "¿qué llevo a Cartagena en julio?"

Requiere ``ROVER_LLM_API_KEY`` en ``apps/backend/.env`` (o en el entorno). Los
tests NO usan este script ni la key real: ver ``tests/test_llm.py``.
"""

import asyncio
import sys

from app.core.logging import configure_logging
from app.services.llm import LLMError, Message, Role, get_llm_provider

PREGUNTA_POR_DEFECTO = "En una frase: ¿qué tal el clima en Bogotá en julio?"


async def main() -> int:
    # Logs en texto y por stdout: aquí lo que interesa es LEER la línea de
    # instrumentación (tokens, latencia, cache hit), no parsearla.
    configure_logging(log_format="text")

    pregunta = sys.argv[1] if len(sys.argv) > 1 else PREGUNTA_POR_DEFECTO
    mensajes = [Message(role=Role.USER, content=pregunta)]

    try:
        proveedor = get_llm_provider()
        print(f"\n→ modelo: {proveedor.model}\n→ pregunta: {pregunta}\n")

        print("--- completado (sin streaming) ---")
        respuesta = await proveedor.complete(mensajes)
        print(respuesta.text)
        print(f"[usage: {respuesta.usage}]\n")

        print("--- streaming (debe aparecer a trozos) ---")
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


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
