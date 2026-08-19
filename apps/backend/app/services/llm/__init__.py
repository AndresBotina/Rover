"""Capa de abstracción del proveedor de LLM (HU-2.1).

Rover no habla con DeepSeek: habla con **un proveedor de LLM** en abstracto.
DeepSeek V4 Flash es hoy la única implementación, y es intercambiable. Misma
jugada que ``RateLimitStore`` en la HU-1.7 (interfaz estable, implementación
desechable) y misma disciplina que ``services/auth.py`` con Supabase (los
errores y la forma del proveedor se quedan dentro).

Cómo se usa desde el resto del backend — siempre así, nunca importando
``deepseek``:

    from app.services.llm import Message, Role, get_llm_provider

    provider = get_llm_provider()                      # capacidad: texto
    respuesta = await provider.complete([Message(role=Role.USER, content="hola")])

    async for trozo in provider.stream(mensajes):      # camino de la HU-2.4
        enviar_por_sse(trozo.text)

Mapa de los módulos:

- ``base.py``            — tipos de dominio, ``Capability`` y el ``Protocol``.
- ``errors.py``          — excepciones de dominio (nada del proveedor sale de aquí).
- ``prompt.py``          — carga del system prompt; el texto vive en ``prompts/``.
- ``deepseek.py``        — implementación concreta sobre el endpoint OpenAI-compatible.
- ``instrumentation.py`` — uso/latencia/caché por llamada; semilla del router futuro.
- ``registry.py``        — quién atiende cada capacidad (el *seam* de selección).
"""

from app.services.llm.base import (
    Capability,
    Completion,
    CompletionChunk,
    LLMProvider,
    Message,
    Role,
    Usage,
)
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMCapabilityUnavailable,
    LLMError,
    LLMNotConfigured,
    LLMProviderError,
    LLMQuotaExceeded,
    LLMRateLimited,
    LLMUnavailable,
)
from app.services.llm.prompt import DEFAULT_SYSTEM_PROMPT
from app.services.llm.registry import (
    get_llm_provider,
    reset_llm_providers,
    set_llm_provider,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "Capability",
    "Completion",
    "CompletionChunk",
    "LLMAuthError",
    "LLMBadRequest",
    "LLMCapabilityUnavailable",
    "LLMError",
    "LLMNotConfigured",
    "LLMProvider",
    "LLMProviderError",
    "LLMQuotaExceeded",
    "LLMRateLimited",
    "LLMUnavailable",
    "Message",
    "Role",
    "Usage",
    "get_llm_provider",
    "reset_llm_providers",
    "set_llm_provider",
]
