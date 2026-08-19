"""Quién atiende cada capacidad: el ÚNICO sitio que sabe qué proveedor existe.

Es el *seam* de **selección por capacidad** que pide la HU-2.1. El agente
—hoy nadie, desde la HU-2.4 el endpoint de chat— pedirá siempre lo mismo:

    provider = get_llm_provider()                     # texto (el default)
    provider = get_llm_provider(Capability.VISION)    # el día que exista

y jamás construirá un ``DeepSeekProvider`` a mano. Esa disciplina es lo que
hace que añadir un segundo modelo sea **una línea en este archivo**:

    _CONSTRUCTORES[Capability.VISION] = _construir_proveedor_de_vision

sin tocar el agente, ni el endpoint, ni los tipos de dominio.

## Lo que este módulo NO hace, a propósito

**No enruta por dificultad.** Elegir un modelo más caro porque la pregunta
parece difícil está DIFERIDO, y su disparador es la instrumentación de
``instrumentation.py``: cuando esos datos muestren dónde falla el modelo
barato, el router se diseñará contra ejemplos reales. Si se implementara aquí
hoy, se estaría adivinando (y el sitio donde encajaría sería este mismo, con la
petición como entrada además de la capacidad).

**No mantiene un cliente HTTP vivo.** El proveedor se construye una vez por
proceso porque su configuración no cambia, pero cada llamada abre y cierra su
conexión (ver ``deepseek.py``): no hay estado atado a un event loop.

## Sustituirlo en tests

``set_llm_provider(doble)`` inyecta cualquier implementación del ``Protocol`` y
``reset_llm_providers()`` deshace, igual que ``reset_rate_limit_store`` en la
HU-1.7. Es lo que permitirá probar el endpoint SSE de la HU-2.4 sin key y sin
red.
"""

from app.core.config import settings
from app.services.llm.base import Capability, LLMProvider
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.errors import LLMCapabilityUnavailable, LLMNotConfigured

#: Proveedores ya construidos, por capacidad. Perezoso a propósito: construirlo
#: al importar exigiría la key para arrancar la app, y local/test deben poder
#: levantar sin ella (mismo criterio que el engine de base de datos, HU-1.1).
_proveedores: dict[Capability, LLMProvider] = {}


def _construir_proveedor_de_texto() -> LLMProvider:
    """Arma el proveedor de texto con lo que diga la config.

    Es el ÚNICO punto del código que lee la configuración del LLM: el proveedor
    la recibe por constructor, así que es aquí donde se cambia si mañana la
    key sale de un gestor de secretos en vez de una variable de entorno.
    """
    if settings.llm_api_key is None:
        raise LLMNotConfigured(
            "El proveedor de LLM no está configurado (falta ROVER_LLM_API_KEY); ver .env.example."
        )
    return DeepSeekProvider(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        thinking=settings.llm_thinking,
    )


def get_llm_provider(capability: Capability = Capability.TEXT) -> LLMProvider:
    """Devuelve el proveedor que atiende ``capability``.

    Hoy solo hay uno, de texto, y por eso el default cubre el 100 % de los
    llamadores. Pedir una capacidad sin proveedor levanta
    ``LLMCapabilityUnavailable`` en vez de caer al de texto en silencio: un
    modelo de texto al que se le manda una imagen no protesta, responde mal —y
    ese fallo aparecería como "el agente alucina", no como "falta configurar el
    modelo de visión".
    """
    proveedor = _proveedores.get(capability)
    if proveedor is not None:
        return proveedor

    if capability is not Capability.TEXT:
        raise LLMCapabilityUnavailable(
            f"No hay proveedor de LLM para la capacidad '{capability.value}'."
        )

    proveedor = _construir_proveedor_de_texto()
    _proveedores[capability] = proveedor
    return proveedor


def set_llm_provider(provider: LLMProvider, *, capability: Capability = Capability.TEXT) -> None:
    """Registra (o sustituye) el proveedor de una capacidad.

    Dos usos: inyectar un doble en tests, y —el día que llegue— enchufar el
    proveedor de visión desde el arranque de la app.
    """
    _proveedores[capability] = provider


def reset_llm_providers() -> None:
    """Olvida los proveedores construidos (aislamiento entre tests)."""
    _proveedores.clear()
