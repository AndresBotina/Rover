"""Tests de la estructura de la API y de su documentación OpenAPI (HU-1.9).

No prueban lógica de negocio, sino el CONTRATO visible: que todo cuelgue de
/v1, que cada operación esté etiquetada por dominio, que las rutas protegidas
se anuncien como tales y que las docs se puedan apagar en producción.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import app, create_app

# Rutas protegidas por el middleware: deben declarar el esquema de seguridad.
_RUTAS_PROTEGIDAS = {
    ("/v1/users/me", "get"),
    ("/v1/users/me", "patch"),
    ("/v1/chat", "post"),
    ("/v1/chat/sessions", "get"),
    ("/v1/chat/sessions/{session_id}", "get"),
    ("/v1/chat/sessions/{session_id}", "delete"),
}


@pytest.fixture
def spec() -> dict[str, Any]:
    return app.openapi()


def test_todas_las_rutas_cuelgan_de_v1(spec: dict[str, Any]) -> None:
    assert spec["paths"], "el esquema no expone ninguna ruta"
    assert all(path.startswith("/v1/") for path in spec["paths"])


def test_metadatos_de_la_app(spec: dict[str, Any]) -> None:
    assert spec["info"]["title"] == "Rover API"
    # La versión sale de app.__version__ vía settings: una sola fuente de verdad.
    assert spec["info"]["version"] == settings.version
    assert spec["info"]["description"].strip()


def test_cada_operacion_tiene_tag_de_dominio_y_resumen(spec: dict[str, Any]) -> None:
    tags_declarados = {tag["name"] for tag in spec["tags"]}
    assert tags_declarados == {"health", "auth", "users", "chat"}

    for path, operaciones in spec["paths"].items():
        for metodo, operacion in operaciones.items():
            etiquetas = set(operacion.get("tags", []))
            assert etiquetas <= tags_declarados, f"{metodo} {path} usa un tag sin describir"
            assert etiquetas, f"{metodo} {path} no está agrupada por dominio"
            assert operacion.get("summary"), f"{metodo} {path} no tiene summary"
            assert operacion.get("description"), f"{metodo} {path} no tiene description"


def test_los_tags_estan_descritos(spec: dict[str, Any]) -> None:
    assert all(tag.get("description") for tag in spec["tags"])


def test_las_rutas_protegidas_declaran_el_esquema_bearer(spec: dict[str, Any]) -> None:
    esquema = spec["components"]["securitySchemes"]["SupabaseAccessToken"]
    assert esquema["type"] == "http"
    assert esquema["scheme"] == "bearer"

    protegidas = {
        (path, metodo)
        for path, operaciones in spec["paths"].items()
        for metodo, operacion in operaciones.items()
        if operacion.get("security")
    }
    assert protegidas == _RUTAS_PROTEGIDAS


def test_las_rutas_protegidas_documentan_401_y_503(spec: dict[str, Any]) -> None:
    for path, metodo in _RUTAS_PROTEGIDAS:
        respuestas = spec["paths"][path][metodo]["responses"]
        assert {"401", "503"} <= respuestas.keys()


def test_los_errores_del_login_estan_documentados(spec: dict[str, Any]) -> None:
    """Los códigos que el cliente debe manejar aparecen en el esquema."""
    respuestas = spec["paths"]["/v1/auth/login"]["post"]["responses"]
    assert {"200", "401", "403", "422", "429", "503"} <= respuestas.keys()


def test_todos_los_errores_documentados_usan_el_formato_unico(spec: dict[str, Any]) -> None:
    """Ningún error puede quedar documentado con otro esquema (HU-1.8).

    Incluye el 422 que FastAPI añade solo: su `HTTPValidationError` ya no es lo
    que devuelve la API, así que se declara a mano donde aparece.
    """
    for path, operaciones in spec["paths"].items():
        for metodo, operacion in operaciones.items():
            for code, respuesta in operacion["responses"].items():
                if int(code) < 400:
                    continue
                esquema = respuesta["content"]["application/json"]["schema"]
                assert esquema["$ref"].endswith("/ErrorResponse"), (
                    f"{metodo} {path} → {code} no documenta el formato único"
                )
    # Y el esquema viejo desaparece del componente: nada lo referencia ya.
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_hay_ejemplos_en_los_cuerpos_de_entrada(spec: dict[str, Any]) -> None:
    for modelo in ("RegisterRequest", "LoginRequest", "ProfileUpdateRequest"):
        assert spec["components"]["schemas"][modelo].get("examples"), f"{modelo} sin ejemplo"


def test_auth_me_ya_no_existe(spec: dict[str, Any]) -> None:
    """Consolidado en /v1/users/me (HU-1.9): un subconjunto con el mismo costo."""
    assert "/v1/auth/me" not in spec["paths"]

    with TestClient(app) as client:
        assert client.get("/v1/auth/me").status_code == 404


# --- Docs apagables en producción --------------------------------------------


def _app_con_env(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> TestClient:
    """Construye una app nueva con los settings dados (create_app los lee)."""
    for campo, valor in overrides.items():
        monkeypatch.setattr(settings, campo, valor)
    return TestClient(create_app())


def test_en_local_las_docs_estan_disponibles(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app_con_env(monkeypatch, env="local", enable_docs=None)

    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_en_produccion_las_docs_estan_apagadas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin esquema no hay mapa de la API para quien haga reconocimiento."""
    client = _app_con_env(monkeypatch, env="production", enable_docs=None)

    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    # La API en sí sigue funcionando: lo que se apaga es la documentación.
    assert client.get("/v1/health").status_code == 200


def test_la_variable_dedicada_manda_sobre_el_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """ROVER_ENABLE_DOCS permite abrirlas en producción (o cerrarlas en local)."""
    abiertas = _app_con_env(monkeypatch, env="production", enable_docs=True)
    assert abiertas.get("/docs").status_code == 200

    cerradas = _app_con_env(monkeypatch, env="local", enable_docs=False)
    assert cerradas.get("/docs").status_code == 404


def test_el_default_por_ambiente_se_calcula_en_settings() -> None:
    assert Settings(_env_file=None, env="local").docs_enabled is True
    assert Settings(_env_file=None, env="test").docs_enabled is True
    # Producción exige los secretos; se simulan para poder construir Settings.
    produccion = Settings(
        _env_file=None,
        env="production",
        database_url="postgresql://x",
        supabase_url="https://x.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
        llm_api_key="llm",
    )
    assert produccion.docs_enabled is False
    assert produccion.model_copy(update={"enable_docs": True}).docs_enabled is True
