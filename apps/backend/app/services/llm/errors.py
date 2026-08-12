"""Excepciones de dominio del LLM: lo único que ve el resto del backend.

Mismo contrato que las de ``services/auth.py`` (HU-1.3), por las mismas
razones y con la misma disciplina:

- El **mensaje** (``str(exc)``) es SEGURO para enseñar a un usuario. No lleva
  diagnóstico del proveedor, ni la URL, ni por supuesto la API key.
- El diagnóstico del proveedor —status HTTP, ``code``/``type`` y su mensaje—
  viaja en atributos APARTE y es SOLO para los logs del servidor.
- La traducción se hace en el módulo del proveedor. Aquí no hay nada de
  DeepSeek: quien captura ``LLMRateLimited`` no sabe (ni le importa) quién
  respondió 429.

Estas clases NO son códigos de error de la API. El puente al contrato de la
HU-1.8 (``ApiError`` + ``ErrorCode``) lo pondrá el endpoint de chat en la
HU-2.4, que es quien sabe traducir "el proveedor está saturado" al ``code`` y
al status que corresponde en HTTP; el servicio no tiene por qué conocer HTTP.
"""


class LLMError(Exception):
    """Fallo hablando con el proveedor de LLM, ya traducido a dominio."""

    def __init__(
        self,
        message: str,
        *,
        provider_status: int | None = None,
        provider_error_code: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_status = provider_status
        self.provider_error_code = provider_error_code
        self.provider_message = provider_message


class LLMNotConfigured(LLMError):
    """Falta la configuración del proveedor (típicamente ``ROVER_LLM_API_KEY``).

    Es un error de OPERACIÓN, no del usuario: en producción no puede ocurrir
    (``_REQUIRED_IN_PRODUCTION`` corta el arranque), y en local significa que
    falta el ``.env``.
    """


class LLMAuthError(LLMError):
    """El proveedor rechazó nuestras credenciales (401/403).

    Nunca es culpa de quien usa Rover: la key es inválida, fue revocada o no
    tiene permiso para el modelo pedido.
    """


class LLMQuotaExceeded(LLMError):
    """La CUENTA de Rover ante el proveedor se quedó sin saldo o sin cuota.

    Distinta de ``LLMRateLimited``: ahí hay que esperar, aquí hay que pagar.
    Reintentar no arregla nada.
    """


class LLMRateLimited(LLMError):
    """El proveedor está limitando nuestra tasa de peticiones (429).

    Es transitorio: reintentar más tarde tiene sentido. No confundir con el
    rate limiting PROPIO de la API (HU-1.7), que acota lo que pide un cliente.
    """


class LLMBadRequest(LLMError):
    """El proveedor rechazó la petición por su forma o su contenido (4xx).

    Contexto demasiado largo, parámetro fuera de rango o filtro de contenido:
    reintentar tal cual volvería a fallar.
    """


class LLMUnavailable(LLMError):
    """No se pudo obtener respuesta: red caída, timeout o 5xx del proveedor.

    Es el caso que degrada la conversación, y por eso está separado del resto:
    la HU-2.4 puede decidir reintentar o avisar sin adivinar por el status.
    """


class LLMProviderError(LLMError):
    """Fallo desconocido o respuesta con forma inesperada.

    Red de seguridad: antes esto que dejar escapar una excepción del cliente
    HTTP con la forma del proveedor dentro.
    """


class LLMCapabilityUnavailable(LLMError):
    """No hay ningún proveedor registrado para la capacidad pedida.

    Hoy lo levanta ``get_llm_provider(Capability.VISION)``: el seam existe,
    pero la implementación de visión no. Es deliberado que falle CLARO en vez
    de caer en silencio al proveedor de texto — un modelo de texto al que se le
    manda una imagen no avisa, simplemente responde mal.
    """
