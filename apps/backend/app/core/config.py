"""Configuración del backend, leída de variables de entorno.

Usa pydantic-settings. Las variables llevan el prefijo ``ROVER_`` para no chocar
con variables genéricas del sistema (p. ej. ``ROVER_ENV``, ``ROVER_APP_NAME``).
Sin secretos por ahora.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    """Settings de la app con valores por defecto sensatos."""

    model_config = SettingsConfigDict(
        env_prefix="ROVER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Rover"
    env: str = "local"
    # La versión tiene una sola fuente de verdad: app.__version__.
    version: str = __version__


@lru_cache
def get_settings() -> Settings:
    """Devuelve los settings (cacheados) de la app."""
    return Settings()


settings = get_settings()
