"""Tests de CORS por ambiente (HU-1.11).

Qué se prueba aquí y qué NO: CORS lo aplica el NAVEGADOR, no el servidor. Un
origen no permitido no recibe un 403 — recibe una respuesta normal SIN la
cabecera ``Access-Control-Allow-Origin``, y es el navegador el que entonces le
niega el contenido al JavaScript de esa página. Por eso los tests aserta la
PRESENCIA o AUSENCIA de cabeceras, no códigos de estado. El control de acceso
de verdad sigue siendo el Bearer (HU-1.6) y los límites (HU-1.7).
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.middleware import (
    CORS_CABECERAS_EXPUESTAS,
    CORS_MAX_AGE_SEGUNDOS,
)
from app.core.config import Settings, settings
from app.main import create_app

_WEB_LOCAL = "http://localhost:3000"
_WEB_PROD = "https://rover.app"
_AJENO = "https://sitio-ajeno.example"

_ACAO = "access-control-allow-origin"


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    env: str = "local",
    cors_origins: str | None = None,
    **overrides: object,
) -> TestClient:
    """App nueva con la config dada (el CORS se monta al crear la app)."""
    monkeypatch.setattr(settings, "env", env)
    monkeypatch.setattr(settings, "cors_origins", cors_origins)
    for campo, valor in overrides.items():
        monkeypatch.setattr(settings, campo, valor)
    return TestClient(create_app())


def _settings_produccion(cors_origins: str | None = None) -> Settings:
    """Settings de producción; los secretos obligatorios van simulados."""
    return Settings(
        _env_file=None,
        env="production",
        cors_origins=cors_origins,
        database_url="postgresql://x",
        supabase_url="https://x.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
        llm_api_key="llm",
    )


# --- Orígenes permitidos y denegados -----------------------------------------


def test_un_origen_permitido_recibe_las_cabeceras_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)

    respuesta = client.get("/v1/health", headers={"Origin": _WEB_LOCAL})

    assert respuesta.status_code == 200
    assert respuesta.headers[_ACAO] == _WEB_LOCAL
    # Sin `Vary: Origin`, una caché intermedia podría servirle a un origen la
    # respuesta que ya guardó para otro, con su cabecera de permiso incluida.
    assert "origin" in respuesta.headers["vary"].lower()


def test_un_origen_no_permitido_no_recibe_permiso(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)

    respuesta = client.get("/v1/health", headers={"Origin": _AJENO})

    # La petición se ejecuta igual (CORS no es un cortafuegos), pero sale sin
    # la cabecera de permiso: el navegador no le entregará el cuerpo a esa web.
    assert respuesta.status_code == 200
    assert _ACAO not in respuesta.headers


def test_localhost_y_127_0_0_1_son_ambos_orígenes_de_desarrollo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Para un navegador son orígenes DISTINTOS: la comparación es textual."""
    client = _client(monkeypatch)

    for origen in ("http://localhost:3000", "http://127.0.0.1:3000"):
        respuesta = client.get("/v1/health", headers={"Origin": origen})
        assert respuesta.headers[_ACAO] == origen


# --- Preflight ---------------------------------------------------------------


def test_el_preflight_de_un_post_con_json_y_bearer_pasa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso real: la web pide permiso antes de un POST con cuerpo JSON."""
    client = _client(monkeypatch)

    respuesta = client.options(
        "/v1/auth/login",
        headers={
            "Origin": _WEB_LOCAL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.headers[_ACAO] == _WEB_LOCAL
    assert "POST" in respuesta.headers["access-control-allow-methods"]
    assert "content-type" in respuesta.headers["access-control-allow-headers"].lower()
    assert respuesta.headers["access-control-max-age"] == str(CORS_MAX_AGE_SEGUNDOS)


def test_authorization_esta_entre_las_cabeceras_permitidas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin esto, ninguna ruta protegida sería llamable desde el navegador."""
    client = _client(monkeypatch)

    respuesta = client.options(
        "/v1/users/me",
        headers={
            "Origin": _WEB_LOCAL,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert respuesta.status_code == 200
    permitidas = respuesta.headers["access-control-allow-headers"].lower()
    assert "authorization" in permitidas
    assert "PATCH" in respuesta.headers["access-control-allow-methods"]


@pytest.mark.parametrize("metodo", ["GET", "POST", "PATCH"])
def test_el_preflight_permite_los_metodos_que_la_api_usa(
    monkeypatch: pytest.MonkeyPatch, metodo: str
) -> None:
    client = _client(monkeypatch)

    respuesta = client.options(
        "/v1/users/me",
        headers={
            "Origin": _WEB_LOCAL,
            "Access-Control-Request-Method": metodo,
        },
    )

    assert respuesta.status_code == 200
    assert metodo in respuesta.headers["access-control-allow-methods"]


def test_el_preflight_de_un_origen_ajeno_no_da_permiso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    respuesta = client.options(
        "/v1/auth/login",
        headers={
            "Origin": _AJENO,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert _ACAO not in respuesta.headers


# --- Credenciales y cabeceras legibles ---------------------------------------


def test_no_se_anuncian_credenciales(monkeypatch: pytest.MonkeyPatch) -> None:
    """La sesión viaja en Authorization, no en cookies (ver docs/auth.md).

    Como nunca se permiten credenciales, la combinación insegura
    ``"*"`` + credenciales no puede darse por construcción.
    """
    client = _client(monkeypatch)

    respuesta = client.get("/v1/health", headers={"Origin": _WEB_LOCAL})

    assert "access-control-allow-credentials" not in respuesta.headers


def test_las_cabeceras_del_rate_limit_son_legibles_por_la_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin exponerlas, `ApiError.retryAfterSeconds` sería siempre null en web."""
    client = _client(monkeypatch)

    respuesta = client.get("/v1/health", headers={"Origin": _WEB_LOCAL})

    expuestas = respuesta.headers["access-control-expose-headers"].lower()
    for cabecera in CORS_CABECERAS_EXPUESTAS:
        assert cabecera.lower() in expuestas


# --- Orden en la pila: el 429 tiene que llegar legible al navegador ----------


def test_el_429_del_rate_limit_sale_con_cabeceras_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORS envuelve al rate limiter (HU-1.7), no al revés.

    Si fuera al revés, el navegador le ocultaría el 429 a la web como un error
    de CORS y esta no podría distinguirlo de una caída, ni leer `Retry-After`.
    """
    client = _client(
        monkeypatch,
        rate_limit_enabled=True,
        rate_limit_default_limit=1,
        rate_limit_default_window_seconds=60,
    )
    cabeceras = {"Origin": _WEB_LOCAL}

    primera = client.get("/v1/users/me", headers=cabeceras)
    segunda = client.get("/v1/users/me", headers=cabeceras)

    assert primera.status_code == 401  # sin token, pero dentro del cupo
    assert segunda.status_code == 429
    assert segunda.headers[_ACAO] == _WEB_LOCAL
    assert segunda.headers["retry-after"]


def test_el_preflight_no_consume_cupo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contrapartida asumida del orden: OPTIONS no llega al rate limiter.

    Es barato (ni ruta, ni base, ni JWKS) y no abre nada: quien quiera abusar
    manda peticiones reales, que sí cuentan.
    """
    client = _client(
        monkeypatch,
        rate_limit_enabled=True,
        rate_limit_default_limit=1,
        rate_limit_default_window_seconds=60,
    )
    preflight = {
        "Origin": _WEB_LOCAL,
        "Access-Control-Request-Method": "POST",
    }

    for _ in range(5):
        assert client.options("/v1/auth/login", headers=preflight).status_code == 200

    # El cupo sigue intacto para la petición de verdad.
    assert client.get("/v1/users/me", headers={"Origin": _WEB_LOCAL}).status_code == 401


# --- Producción --------------------------------------------------------------


def test_en_produccion_sin_origenes_configurados_no_pasa_ninguno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed: se cierra a los navegadores, NUNCA se cae a "*"."""
    client = _client(monkeypatch, env="production", cors_origins=None)

    respuesta = client.get("/v1/health", headers={"Origin": _WEB_PROD})

    assert respuesta.status_code == 200  # la API sigue sirviendo (móvil, curl)
    assert _ACAO not in respuesta.headers


def test_en_produccion_solo_pasan_los_origenes_configurados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        monkeypatch, env="production", cors_origins=f"{_WEB_PROD},https://www.rover.app"
    )

    permitido = client.get("/v1/health", headers={"Origin": _WEB_PROD})
    ajeno = client.get("/v1/health", headers={"Origin": _AJENO})
    # Y los de desarrollo dejan de valer: no son un default en producción.
    local = client.get("/v1/health", headers={"Origin": _WEB_LOCAL})

    assert permitido.headers[_ACAO] == _WEB_PROD
    assert _ACAO not in ajeno.headers
    assert _ACAO not in local.headers


def test_en_produccion_el_comodin_impide_arrancar() -> None:
    """Fail-fast: mejor no arrancar que servir la API a cualquier página web."""
    with pytest.raises(ValidationError, match="ROVER_CORS_ORIGINS no puede ser"):
        _settings_produccion(cors_origins="*")

    # Tampoco colado dentro de una lista por lo demás legítima.
    with pytest.raises(ValidationError, match="ROVER_CORS_ORIGINS no puede ser"):
        _settings_produccion(cors_origins=f"{_WEB_PROD}, *")


def test_fuera_de_produccion_el_comodin_se_admite_como_escape_hatch() -> None:
    assert Settings(_env_file=None, env="local", cors_origins="*").cors_allowed_origins == ["*"]


# --- Resolución de la config -------------------------------------------------


def test_defaults_por_ambiente() -> None:
    dev = ["http://localhost:3000", "http://127.0.0.1:3000"]

    assert Settings(_env_file=None, env="local").cors_allowed_origins == dev
    assert Settings(_env_file=None, env="test").cors_allowed_origins == dev
    # En producción, ninguno mientras no se configuren explícitamente.
    assert _settings_produccion().cors_allowed_origins == []


def test_la_lista_separada_por_comas_se_limpia() -> None:
    crudo = f" {_WEB_PROD} , https://www.rover.app ,, "

    resuelto = Settings(_env_file=None, env="local", cors_origins=crudo).cors_allowed_origins

    assert resuelto == [_WEB_PROD, "https://www.rover.app"]


def test_una_cadena_vacia_significa_ningun_origen() -> None:
    """Explícito manda sobre el default del ambiente."""
    assert Settings(_env_file=None, env="local", cors_origins="").cors_allowed_origins == []
