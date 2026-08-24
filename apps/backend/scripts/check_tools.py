"""Comprobación manual del tool-calling contra las APIs REALES (no es un test).

Ejerce el turno completo —modelo de verdad, clima de verdad, loop de verdad—
sin levantar el servidor ni pedir un token, y enseña **lo que un test mockeado
no puede confirmar**:

1. que **DeepSeek decide** llamar a ``get_weather`` con la descripción que se le
   dio (o que decide NO llamarla, si la pregunta no la necesita),
2. que la **key de OpenWeatherMap está activa** — una recién creada responde
   401 durante un rato,
3. y **qué quedaría en ``tool_steps``**: los pasos se imprimen aquí, que es el
   único sitio donde se enseñan (por el stream y por la API no salen).

    cd apps/backend
    uv run python -m scripts.check_tools
    uv run python -m scripts.check_tools "¿me llevo chaqueta a Medellín?"

Requiere ``ROVER_LLM_API_KEY`` y ``ROVER_WEATHER_API_KEY`` en
``apps/backend/.env`` (o en el entorno). Sin la del clima el catálogo sale
vacío y el script lo dice: es el mismo camino que sigue la app.

Los tests NO usan este script ni las keys reales: ver ``tests/test_tools.py``,
``tests/test_chat_tools.py`` y ``tests/test_weather.py``.
"""

import asyncio
import json
import sys

from app.core.logging import configure_logging
from app.services.llm import (
    DEFAULT_SYSTEM_PROMPT,
    LLMError,
    Message,
    Role,
    get_llm_provider,
)
from app.services.tools import TextDelta, ToolLoop, ToolStatus, get_tool_registry

PREGUNTA_POR_DEFECTO = "¿Qué tal el clima en Bogotá ahora mismo?"


async def main() -> int:
    # Logs en texto y por stdout: aquí interesa LEER las líneas ``app.llm`` (una
    # por vuelta del loop) y ``app.tools`` (una por ejecución), no parsearlas.
    configure_logging(log_format="text")

    pregunta = sys.argv[1] if len(sys.argv) > 1 else PREGUNTA_POR_DEFECTO
    registro = get_tool_registry()

    print(f"\n=== Herramientas ofrecidas al modelo: {len(registro)} ===")
    for spec in registro.specs():
        print(f"  · {spec.name}: {spec.description[:70]}…")
    if len(registro) == 0:
        print("  (ninguna: falta ROVER_WEATHER_API_KEY — ver .env.example)")

    try:
        proveedor = get_llm_provider()
    except LLMError as exc:
        print(f"\nNo hay proveedor de LLM: {exc}")
        return 1

    loop = ToolLoop(proveedor, registry=registro, system_prompt=DEFAULT_SYSTEM_PROMPT)

    print(f"\n=== Pregunta ===\n{pregunta}\n\n=== Respuesta (streaming) ===")
    try:
        async for evento in loop.run([Message(role=Role.USER, content=pregunta)]):
            match evento:
                case TextDelta(text=texto):
                    print(texto, end="", flush=True)
                case ToolStatus(tool=herramienta, label=etiqueta):
                    # Lo ÚNICO que el cliente ve de la fase de herramienta.
                    print(f"\n  [{herramienta}] {etiqueta}", flush=True)
    except LLMError as exc:
        print(f"\n\nFalló la llamada al modelo: {exc} (status={exc.provider_status})")
        return 1
    print()

    # Los pasos intermedios: se persisten en ``messages.tool_steps`` y NO salen
    # ni por el stream ni por ``GET /v1/chat/sessions/{id}``. Aquí se imprimen
    # justamente porque es lo que no se puede mirar desde fuera.
    print("\n=== tool_steps (interno: esto NO lo ve el cliente) ===")
    if not loop.steps:
        print("  (el modelo respondió sin usar herramientas)")
    else:
        print(json.dumps(loop.steps, ensure_ascii=False, indent=2))

    fallidos = [p for p in loop.steps if p["status"] != "ok"]
    if fallidos:
        print(
            "\nOJO: alguna herramienta no completó. Si es el clima con un 401, "
            "revisa arriba la línea del log: una key NUEVA de OpenWeatherMap "
            "tarda en activarse."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
