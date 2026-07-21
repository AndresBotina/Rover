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

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

# Ambientes soportados. Cualquier otro valor de ROVER_ENV impide arrancar.
Environment = Literal["local", "test", "production"]

# .env del backend (apps/backend/.env), anclado a este archivo para que la
# carga no dependa del directorio desde el que se lance uvicorn o pytest.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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

    # Campos que no pueden faltar cuando env == "production".
    _REQUIRED_IN_PRODUCTION: ClassVar[tuple[str, ...]] = (
        "database_url",
        "supabase_url",
        "supabase_anon_key",
        "supabase_service_role_key",
    )

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
