"""Configuración por ambiente del backend, leída de variables de entorno.

Usa pydantic-settings con prefijo ``ROVER_``. Las variables llegan por dos
caminos, con el MISMO código:

- **local**: de ``apps/backend/.env`` (copiar de ``.env.example``; el real
  está git-ignorado) o del entorno del shell.
- **production** (Render): del entorno del PaaS (panel Environment). No hay
  archivo .env en producción.

Regla de oro: NINGÚN secreto en el código ni en git, nunca. Los secretos
entran siempre por variable de entorno.

Fail-fast: ``settings`` se construye al importar este módulo, así que una
config inválida (ambiente desconocido, variable obligatoria ausente) impide
ARRANCAR la app con un error claro, en vez de romper a mitad de ejecución.
"""

from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__
from app.core.logging import LogFormat

# Ambientes soportados. Cualquier otro valor de ROVER_ENV impide arrancar.
Environment = Literal["local", "test", "production"]

# .env del backend (apps/backend/.env), anclado a este archivo para que la
# carga no dependa del directorio desde el que se lance uvicorn o pytest.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Orígenes de desarrollo permitidos por defecto FUERA de producción, para que
# la web de la Épica 3 arranque sin tener que configurar nada. ``localhost`` y
# ``127.0.0.1`` son orígenes DISTINTOS para un navegador (la comparación es
# textual, no por resolución de nombres), así que van los dos: si no, arrancar
# el dev server por una u otra forma daría resultados distintos.
_DEV_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


class Settings(BaseSettings):
    """Settings de la app. Defaults sensatos SOLO para lo no sensible."""

    model_config = SettingsConfigDict(
        env_prefix="ROVER_",
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Rover"
    env: Environment = "local"
    # La versión tiene una sola fuente de verdad: app.__version__.
    version: str = __version__

    # --- Documentación interactiva (HU-1.9) ----------------------------------
    # ``None`` = decide el ambiente (ver la propiedad ``docs_enabled``); un
    # booleano explícito en ROVER_ENABLE_DOCS manda sobre esa regla.
    enable_docs: bool | None = None

    # --- Logging (HU-1.12) ---------------------------------------------------
    # ``None`` = decide el ambiente (ver ``effective_log_format``); un valor
    # explícito en ROVER_LOG_FORMAT manda sobre esa regla.
    log_format: LogFormat | None = None

    # --- CORS (HU-1.11) ------------------------------------------------------
    # Orígenes que un NAVEGADOR puede usar para llamar a esta API, como lista
    # separada por comas ("https://rover.app,https://www.rover.app").
    #
    # Se declara CRUDO (str) y se interpreta en ``cors_allowed_origins``, igual
    # que ``enable_docs``/``docs_enabled``: un ``list[str]`` con default fijo
    # no permitiría que el default DEPENDA del ambiente, que es justo lo que
    # aquí importa (dev abierto a localhost, producción cerrada).
    #
    # ``None`` = sin configurar → decide el ambiente. Una cadena VACÍA es
    # distinto: significa "ningún origen", explícitamente.
    cors_origins: str | None = None

    # --- Rate limiting (HU-1.7) ----------------------------------------------
    # Los límites son "N peticiones por ventana". Ver app/core/rate_limit.py
    # para el algoritmo y app/api/middleware.py para dónde se aplica cada uno.

    # Interruptor general. Existe para poder apagarlo en un incidente sin
    # desplegar, y para los tests que no van de rate limiting.
    rate_limit_enabled: bool = True

    # GLOBAL, por IP: protección base de TODA la API. 120/min ≈ 2 req/s
    # sostenidas — holgado para un cliente web o móvil real (una pantalla
    # dispara un puñado de llamadas), y suficiente para que una sola fuente
    # abusiva no monopolice la instancia.
    rate_limit_default_limit: int = Field(default=120, ge=1)
    rate_limit_default_window_seconds: int = Field(default=60, ge=1)

    # AUTH, por IP: /v1/auth/login y /v1/auth/register. Mucho más estricto
    # porque es donde se adivinan contraseñas y se crean cuentas en masa.
    # 10/min deja de sobra para una persona que se equivoca al teclear y
    # reintenta, pero convierte la fuerza bruta en algo inviable: probar un
    # diccionario de 10.000 contraseñas pasaría de minutos a casi 17 horas
    # POR IP, y eso además del límite propio de Supabase.
    rate_limit_auth_limit: int = Field(default=10, ge=1)
    rate_limit_auth_window_seconds: int = Field(default=60, ge=1)

    # USUARIO, por id del token: la cuota de quien ya se autenticó. Es MÁS
    # estricta que la global a propósito — la global protege la máquina de una
    # fuente abusiva, esta acota lo que consume una cuenta, y es la que crecerá
    # con los planes (Épica 5) y las cuotas del agente (Épica 2).
    rate_limit_user_limit: int = Field(default=60, ge=1)
    rate_limit_user_window_seconds: int = Field(default=60, ge=1)

    # PUNTO DE EXTENSIÓN de los límites por plan: multiplica la cuota de
    # usuario de los planes de pago. 1.0 = hoy free y pro valen lo mismo (la
    # HU-1.7 deja el enganche, no la política comercial).
    rate_limit_pro_multiplier: float = Field(default=1.0, gt=0)

    # Saltos de proxy DE CONFIANZA delante de la app, para leer la IP real de
    # X-Forwarded-For sin que el cliente pueda falsificarla. Render pone
    # exactamente uno (su edge). 0 = exposición directa: la cabecera se ignora.
    # Ver ``client_ip`` en app/core/rate_limit.py.
    rate_limit_trusted_proxies: int = Field(default=1, ge=0)

    # --- Secretos (Épica 1) --------------------------------------------------
    # PATRÓN para añadir un secreto:
    #   1. Campo tipado ``SecretStr | None = None`` (opcional: local/test deben
    #      poder arrancar sin él; SecretStr enmascara el valor en logs y repr).
    #   2. Añadir su nombre a ``_REQUIRED_IN_PRODUCTION``: si falta en
    #      producción, la app NO arranca (validador de abajo).
    #   3. Documentarlo en .env.example con placeholder; el valor real va SOLO
    #      en apps/backend/.env (local) o en Render → Environment.

    # URL de Supabase Postgres, TAL CUAL la entrega Supabase (postgresql://…).
    # El driver async (postgresql+asyncpg://) lo añade el código al crear el
    # engine (app/core/database.py); aquí NUNCA se guarda transformada.
    database_url: SecretStr | None = None

    # --- Supabase Auth (HU-1.3): proveedor de identidad ----------------------
    # El backend NO emite JWT propios: delega en Supabase Auth y valida sus
    # tokens (decisión de arquitectura, ver docs/backlog.md § Épica 1).

    # URL del proyecto de Supabase (https://TU-PROYECTO.supabase.co). No es un
    # secreto en sí (es pública en cualquier request al API), pero SÍ es
    # obligatoria: sin ella no hay a quién llamar.
    supabase_url: str | None = None

    # Anon/public key: la usa el registro (HU-1.3) y el login (HU-1.4). Es la
    # llave de permisos de CLIENTE PÚBLICO — SecretStr para no filtrarla en
    # logs/repr, aunque Supabase la considera segura para exponer en clientes.
    supabase_anon_key: SecretStr | None = None

    # Service-role key: permisos ADMINISTRATIVOS totales (se salta RLS). SOLO
    # para el backend, JAMÁS en clientes ni en logs. Queda configurada para
    # operaciones administrativas futuras; HU-1.3 NO la usa (ver
    # app/services/auth.py).
    supabase_service_role_key: SecretStr | None = None

    # --- Proveedor de LLM (HU-2.1) -------------------------------------------
    # El backend habla con la INTERFAZ de app/services/llm, nunca con un
    # proveedor concreto. Estas tres variables son las que deciden CUÁL hay
    # detrás, y por eso ninguna está hardcodeada: cambiar de proveedor
    # OpenAI-compatible (o de modelo) es cambiar entorno, no código.

    # API key del proveedor (SECRETO). Hoy la de DeepSeek. Obligatoria en
    # producción: sin ella el agente no existe.
    llm_api_key: SecretStr | None = None

    # URL base del proveedor. No es secreta. El default apunta a DeepSeek; se
    # respeta el path que traiga (``https://host/v1`` también vale), porque la
    # ruta del endpoint se le CONCATENA — ver app/services/llm/deepseek.py.
    llm_base_url: str = "https://api.deepseek.com"

    # Modelo a usar. Single-model por decisión de arquitectura de la Épica 2;
    # la selección por CAPACIDAD (visión) entraría por el registro de
    # proveedores, no cambiando esta variable (ver app/services/llm/registry.py).
    llm_model: str = "deepseek-v4-flash"

    # --- Parámetros de generación (también de config, no del código) ---------
    # 0.7: conversación con algo de variedad sin irse a inventar. Subirlo hace
    # las respuestas más creativas y menos predecibles; bajarlo a 0 las vuelve
    # casi deterministas (útil para tool-calling, HU-2.6).
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # Techo de tokens de SALIDA por respuesta. Es a la vez un límite de costo y
    # una protección: sin él, un prompt desafortunado puede generar (y cobrar)
    # miles de tokens.
    llm_max_output_tokens: int = Field(default=2048, ge=1)

    # Timeout de una llamada al LLM. Generoso a propósito comparado con el de
    # Supabase Auth (10 s): generar una respuesta larga tarda, y cortar a mitad
    # gasta los tokens igual sin entregar nada.
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    # Modo de razonamiento del modelo. DESACTIVADO por defecto, y no por
    # ahorrar unos tokens: DeepSeek V4 razona por defecto con esfuerzo alto y
    # ese razonamiento se FACTURA como salida. Medido contra el proveedor real,
    # una respuesta conversacional de cuatro frases costaba ~1.163 tokens de
    # salida y ~15 s. Para el chat de Rover —preguntas de viaje, respuestas
    # cortas— eso es pagar y hacer esperar por un razonamiento que no mejora la
    # respuesta.
    #
    # Es config y no una constante porque el router por dificultad (diferido)
    # querrá justo lo contrario para lo que sí lo vale: un itinerario de tres
    # ciudades con presupuesto y fechas. Misma filosofía que ``llm_model``.
    # ``provider_default`` omite el campo del cuerpo, para un proveedor
    # OpenAI-compatible que no lo conozca y rechace parámetros desconocidos
    # (ver app/services/llm/deepseek.py).
    llm_thinking: Literal["disabled", "enabled", "provider_default"] = "disabled"

    # --- Ventana de contexto del chat (HU-2.5) -------------------------------
    # Cuánto historial se le reenvía al modelo en cada turno. Es la palanca de
    # COSTO y de CALIDAD a la vez: cada token de historial se paga en cada
    # turno, y un contexto largo empeora las respuestas ("lost in the middle":
    # el modelo atiende peor a lo que queda en la mitad de una entrada larga).

    # Presupuesto para el HISTORIAL, en tokens. No incluye el system prompt
    # (constante y casi siempre servido de caché) ni el mensaje nuevo (que es
    # innegociable): esos van encima. 4.000 son unos 20-30 turnos de
    # conversación normal — bastante más de lo que un hilo de viaje usa antes
    # de cambiar de tema, y muy lejos del techo del modelo.
    chat_context_token_budget: int = Field(default=4000, ge=0)

    # Caracteres por token que asume el ESTIMADOR (ver app/services/chat.py).
    # 3,0 es deliberadamente PESIMISTA: el español real ronda 3,5-4,0
    # caracteres por token, así que contar a 3,0 sobreestima ~20 % y recorta
    # de más antes que pasarse. Es configurable justamente para poder ajustarlo
    # contra datos: la instrumentación de la HU-2.1 ya reporta el
    # ``llm_input_tokens`` real de cada llamada, así que el error del estimador
    # se MIDE, no se adivina.
    chat_context_chars_per_token: float = Field(default=3.0, gt=0)

    # Campos que no pueden faltar cuando env == "production".
    _REQUIRED_IN_PRODUCTION: ClassVar[tuple[str, ...]] = (
        "database_url",
        "supabase_url",
        "supabase_anon_key",
        "supabase_service_role_key",
        "llm_api_key",
    )

    @property
    def docs_enabled(self) -> bool:
        """Si se sirven ``/docs``, ``/redoc`` y ``/openapi.json``.

        Por defecto: SÍ fuera de producción, NO en producción. El esquema
        OpenAPI es el mapa completo de la API (rutas, cuerpos, códigos de
        error); publicárselo a cualquiera en producción regala trabajo de
        reconocimiento a quien busque superficie de ataque, sin dar nada a
        cambio: los clientes propios (web/móvil) consumen `@rover/shared`, no
        la UI interactiva.

        ``ROVER_ENABLE_DOCS`` fuerza el valor en cualquier ambiente (p. ej.
        activarlas temporalmente en producción para depurar, o apagarlas en
        local). El default por ambiente evita que se olvide apagarlas: para
        exponerlas en producción hay que pedirlo explícitamente.
        """
        if self.enable_docs is not None:
            return self.enable_docs
        return self.env != "production"

    @property
    def effective_log_format(self) -> LogFormat:
        """Formato de los logs, resuelto para el ambiente.

        Por defecto: **JSON en producción**, porque quien lee es una
        herramienta de monitoreo que necesita filtrar por campo (``level``,
        ``request_id``, ``status``) y no sabe leer prosa; **texto fuera de
        producción**, porque quien lee es una persona con una terminal y un
        JSON por línea es hostil para eso.

        ``ROVER_LOG_FORMAT`` (``json``/``text``) fuerza el valor en cualquier
        ambiente — p. ej. ``json`` en local para probar el mismo formato que se
        va a producción.
        """
        if self.log_format is not None:
            return self.log_format
        return "json" if self.env == "production" else "text"

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Orígenes permitidos por el navegador, ya resueltos para el ambiente.

        Sin ``ROVER_CORS_ORIGINS`` configurada:

        - fuera de producción → los orígenes de desarrollo (``_DEV_CORS_ORIGINS``),
          para que la web de la Épica 3 funcione recién clonado el repo;
        - en producción → **lista vacía**: ningún origen. Es la opción segura,
          y es deliberado que NO caiga a ``"*"`` — un despliegue al que se le
          olvidó la variable debe quedar cerrado a los navegadores, no abierto
          a todos. Tampoco corta el arranque (no está en
          ``_REQUIRED_IN_PRODUCTION``): la API sigue siendo perfectamente útil
          sin navegadores —móvil (Expo) no está sujeto a CORS, y curl o un
          servicio tampoco—, así que negarse a arrancar castigaría a esos
          clientes por una variable que solo afecta a la web. El aviso se da
          por log al arrancar (ver ``app/api/middleware.py``).

        Una cadena vacía se respeta tal cual (ningún origen): si se configura
        explícitamente, manda sobre el default del ambiente.
        """
        if self.cors_origins is None:
            return [] if self.env == "production" else list(_DEV_CORS_ORIGINS)
        return [origen.strip() for origen in self.cors_origins.split(",") if origen.strip()]

    @model_validator(mode="after")
    def _reject_wildcard_cors_in_production(self) -> Self:
        """En producción, ``"*"`` es un error de configuración, no un atajo.

        Fail-fast como el resto de la config: mejor no arrancar que servir una
        API que cualquier página web puede llamar desde el navegador de un
        usuario logueado. Fuera de producción sí se admite, como escape hatch
        para depurar desde un origen suelto.
        """
        if self.env == "production" and "*" in self.cors_allowed_origins:
            raise ValueError(
                "config inválida para env='production': ROVER_CORS_ORIGINS no puede ser '*'. "
                "Enumera los orígenes exactos de la web (p. ej. "
                "'https://rover.app,https://www.rover.app'), o déjala sin definir para no "
                "permitir ninguno."
            )
        return self

    @model_validator(mode="after")
    def _fail_fast_if_missing_required(self) -> Self:
        """En producción, corta el arranque si falta un campo obligatorio."""
        if self.env != "production":
            return self
        missing = [name for name in self._REQUIRED_IN_PRODUCTION if getattr(self, name) is None]
        if missing:
            variables = ", ".join(f"ROVER_{name.upper()}" for name in missing)
            raise ValueError(
                f"config incompleta para env='production': faltan variables de entorno "
                f"obligatorias: {variables}. Configúralas en Render → Environment "
                f"(o en tu entorno si estás simulando producción)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Devuelve los settings (cacheados) de la app."""
    return Settings()


settings = get_settings()
