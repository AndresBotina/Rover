"""Tests de la configuración por ambiente y del patrón fail-fast (HU-0.8).

Los tests construyen Settings con ``_env_file=None`` para no depender de un
apps/backend/.env que exista (o no) en la máquina de quien los corre.
"""

from typing import ClassVar

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


class _SettingsConSecreto(Settings):
    """Simula la Épica 1: un secreto opcional, obligatorio en producción.

    Es exactamente el patrón documentado en config.py para añadir secretos
    reales (Supabase, LLM); aquí se prueba el mecanismo sin inventar aún los
    campos de verdad.
    """

    llm_api_key: SecretStr | None = None
    _REQUIRED_IN_PRODUCTION: ClassVar[tuple[str, ...]] = ("llm_api_key",)


def test_defaults_locales_sensatos() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "Rover"
    assert settings.env == "local"
    assert settings.version


def test_lee_variables_de_entorno_con_prefijo_rover(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROVER_APP_NAME", "Rover QA")
    monkeypatch.setenv("ROVER_ENV", "test")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Rover QA"
    assert settings.env == "test"


def test_ambiente_desconocido_impide_arrancar() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, env="chirimoya")

    # El error nombra el campo y los valores permitidos: fail-fast claro.
    message = str(excinfo.value)
    assert "env" in message
    assert "local" in message and "test" in message and "production" in message


def test_en_local_los_secretos_pueden_faltar() -> None:
    settings = _SettingsConSecreto(_env_file=None, env="local")

    assert settings.llm_api_key is None


def test_en_produccion_un_secreto_ausente_corta_el_arranque() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _SettingsConSecreto(_env_file=None, env="production")

    message = str(excinfo.value)
    assert "ROVER_LLM_API_KEY" in message
    assert "production" in message


def test_en_produccion_con_el_secreto_presente_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROVER_LLM_API_KEY", "super-secreto")

    settings = _SettingsConSecreto(_env_file=None, env="production")

    assert settings.llm_api_key is not None
    # SecretStr enmascara el valor: no debe aparecer en repr/logs.
    assert "super-secreto" not in repr(settings)
    assert settings.llm_api_key.get_secret_value() == "super-secreto"
