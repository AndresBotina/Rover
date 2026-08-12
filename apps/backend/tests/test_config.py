"""Tests de la configuración por ambiente y del patrón fail-fast (HU-0.8).

Los tests construyen Settings con ``_env_file=None`` para no depender de un
apps/backend/.env que exista (o no) en la máquina de quien los corre.
"""

from typing import ClassVar

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


class _SettingsConSecreto(Settings):
    """Aísla UN secreto obligatorio para probar el mecanismo de fail-fast.

    Es el patrón documentado en config.py para añadir secretos. Se restringe
    ``_REQUIRED_IN_PRODUCTION`` a un solo campo a propósito: así estos tests
    verifican el MECANISMO (falta → no arranca) sin tener que enumerar todos
    los secretos reales cada vez que se añade uno. Que la key del LLM esté de
    verdad en la lista de producción se comprueba más abajo, contra ``Settings``.
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


# --- Proveedor de LLM (HU-2.1) -----------------------------------------------


def test_el_proveedor_de_llm_trae_defaults_no_secretos() -> None:
    """URL y modelo tienen default; la key NO (es lo único secreto)."""
    settings = Settings(_env_file=None)

    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.llm_api_key is None


def test_los_parametros_de_generacion_salen_de_config() -> None:
    settings = Settings(_env_file=None)

    assert 0.0 <= settings.llm_temperature <= 2.0
    assert settings.llm_max_output_tokens > 0
    assert settings.llm_timeout_seconds > 0


def test_el_proveedor_de_llm_se_cambia_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apuntar a otro proveedor OpenAI-compatible es config, no código."""
    monkeypatch.setenv("ROVER_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("ROVER_LLM_MODEL", "otro/modelo")

    settings = Settings(_env_file=None)

    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.llm_model == "otro/modelo"


def test_una_temperatura_fuera_de_rango_impide_arrancar() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_temperature=5.0)


def test_la_key_del_llm_es_obligatoria_en_produccion() -> None:
    """Sin cerebro no hay agente: la app no debe arrancar a medias."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            _env_file=None,
            env="production",
            database_url="postgresql://x",
            supabase_url="https://x.supabase.co",
            supabase_anon_key="anon",
            supabase_service_role_key="service",
        )

    assert "ROVER_LLM_API_KEY" in str(excinfo.value)


def test_la_key_del_llm_no_aparece_en_el_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROVER_LLM_API_KEY", "sk-de-mentira-pero-secreta")

    settings = Settings(_env_file=None)

    assert "sk-de-mentira-pero-secreta" not in repr(settings)
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "sk-de-mentira-pero-secreta"
