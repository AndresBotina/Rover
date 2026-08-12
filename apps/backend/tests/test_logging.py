"""Tests del logging estructurado y del id de petición (HU-1.12).

Se verifica lo que hace útil un log en producción: que cada línea sea
parseable, que todas las de una misma petición se puedan cruzar por un id, que
ese id llegue al cliente, y que nada de lo que se registra filtre un secreto.
"""

import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core.logging import LogFormat, configure_logging
from app.core.request_context import REQUEST_ID_HEADER, sanitize_request_id
from app.main import create_app

# Credencial de mentira: si aparece en el log, el saneo falló.
_SECRETO_EN_LA_EXCEPCION = "postgresql://postgres:password-secreta@db.x.supabase.co"


@contextmanager
def _capturando(log_format: LogFormat) -> Iterator[io.StringIO]:
    """Redirige el logging a un buffer y restaura la config al terminar."""
    buffer = io.StringIO()
    configure_logging(stream=buffer, log_format=log_format)
    try:
        yield buffer
    finally:
        configure_logging()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """App real más una ruta que revienta a propósito (solo para estos tests)."""
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError(f"fallo interno conectando a {_SECRETO_EN_LA_EXCEPCION}")

    with TestClient(app, raise_server_exceptions=False) as cliente:
        yield cliente


def _lineas_json(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(linea) for linea in buffer.getvalue().splitlines() if linea.strip()]


def _linea_de_acceso(lineas: list[dict[str, Any]]) -> dict[str, Any]:
    accesos = [linea for linea in lineas if linea["logger"] == "app.access"]
    assert len(accesos) == 1, f"se esperaba una línea de acceso, hay {len(accesos)}"
    return accesos[0]


# --- Formato JSON ------------------------------------------------------------


def test_en_json_cada_linea_es_un_objeto_con_los_campos_esperados(client: TestClient) -> None:
    with _capturando("json") as buffer:
        client.get("/v1/health")

    lineas = _lineas_json(buffer)  # json.loads ya falla si alguna no lo es
    assert lineas
    for linea in lineas:
        assert {"timestamp", "level", "logger", "message"} <= linea.keys()
        # ISO 8601 con huso: comparable entre instancias sin adivinar el huso.
        momento = datetime.fromisoformat(linea["timestamp"])
        assert momento.tzinfo is not None


def test_la_linea_de_acceso_trae_metodo_ruta_status_y_duracion(client: TestClient) -> None:
    with _capturando("json") as buffer:
        client.get("/v1/health")

    acceso = _linea_de_acceso(_lineas_json(buffer))
    assert acceso["http_method"] == "GET"
    assert acceso["path"] == "/v1/health"
    assert acceso["status"] == 200
    assert isinstance(acceso["duration_ms"], (int, float))
    assert acceso["level"] == "INFO"


@pytest.mark.parametrize(
    ("ruta", "status_esperado", "nivel"),
    [
        ("/v1/health", 200, "INFO"),
        ("/v1/users/me", 401, "WARNING"),  # sin token
        ("/boom", 500, "ERROR"),
    ],
)
def test_el_nivel_de_la_linea_de_acceso_depende_del_status(
    client: TestClient, ruta: str, status_esperado: int, nivel: str
) -> None:
    with _capturando("json") as buffer:
        respuesta = client.get(ruta)

    assert respuesta.status_code == status_esperado
    acceso = _linea_de_acceso(_lineas_json(buffer))
    assert acceso["level"] == nivel


# --- Id de petición ----------------------------------------------------------


def test_el_request_id_se_devuelve_y_aparece_en_todas_las_lineas(client: TestClient) -> None:
    with _capturando("json") as buffer:
        respuesta = client.get("/v1/users/me")  # 401: emite además la línea de deps

    devuelto = respuesta.headers[REQUEST_ID_HEADER]
    assert devuelto

    lineas = _lineas_json(buffer)
    assert len(lineas) >= 2, "se esperaba más de una línea para poder correlacionar"
    assert all(linea["request_id"] == devuelto for linea in lineas)


def test_se_respeta_un_request_id_entrante(client: TestClient) -> None:
    """Así una traza que empieza en un proxy o en la web sigue siendo la misma."""
    entrante = "trace-abc123"

    with _capturando("json") as buffer:
        respuesta = client.get("/v1/health", headers={REQUEST_ID_HEADER: entrante})

    assert respuesta.headers[REQUEST_ID_HEADER] == entrante
    assert _linea_de_acceso(_lineas_json(buffer))["request_id"] == entrante


def test_sin_cabecera_se_genera_uno_distinto_por_peticion(client: TestClient) -> None:
    primero = client.get("/v1/health").headers[REQUEST_ID_HEADER]
    segundo = client.get("/v1/health").headers[REQUEST_ID_HEADER]

    assert primero and segundo
    assert primero != segundo


@pytest.mark.parametrize(
    "entrante",
    [
        "malicioso\nERROR falsificado: el sistema fue comprometido",  # log injection
        "x" * 65,  # engorda cada línea de la petición
        "con espacios",
        "",
    ],
)
def test_un_request_id_entrante_invalido_se_descarta(client: TestClient, entrante: str) -> None:
    """Entrada no confiable: acaba en los logs y en una cabecera de respuesta."""
    with _capturando("json") as buffer:
        respuesta = client.get("/v1/health", headers={REQUEST_ID_HEADER: entrante})

    devuelto = respuesta.headers[REQUEST_ID_HEADER]
    assert devuelto != entrante
    assert devuelto  # se generó uno propio en su lugar
    assert "falsificado" not in buffer.getvalue()


def test_sanitize_request_id_acepta_solo_lo_seguro() -> None:
    assert sanitize_request_id("abc-123_x.y:z") == "abc-123_x.y:z"
    assert sanitize_request_id("  abc123  ") == "abc123"  # se recorta
    assert sanitize_request_id(None) is None
    assert sanitize_request_id("a\nb") is None
    assert sanitize_request_id("a" * 65) is None
    assert sanitize_request_id("") is None


# --- Correlación con el error_id del 500 (HU-1.8) ----------------------------


def test_en_un_500_el_error_id_y_el_request_id_quedan_ligados(client: TestClient) -> None:
    """Desde cualquiera de los dos se debe poder llegar a la traza completa."""
    with _capturando("json") as buffer:
        respuesta = client.get("/boom")

    assert respuesta.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    error_id = respuesta.json()["error"]["error_id"]
    request_id = respuesta.headers[REQUEST_ID_HEADER]
    assert error_id and request_id

    lineas = _lineas_json(buffer)
    fallo = next(linea for linea in lineas if linea["logger"] == "app.core.errors")
    # Los DOS ids, en la MISMA línea, como campos separados.
    assert fallo["error_id"] == error_id
    assert fallo["request_id"] == request_id
    # Y la traza real, que al cliente nunca se le da.
    assert fallo["exception"]["type"] == "RuntimeError"
    assert "Traceback" in fallo["exception"]["traceback"]


def test_el_500_devuelve_el_id_de_peticion_en_la_cabecera(client: TestClient) -> None:
    """La respuesta del 500 la construye el handler FUERA del middleware."""
    respuesta = client.get("/boom")

    assert respuesta.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert respuesta.headers[REQUEST_ID_HEADER]


# --- Secretos ----------------------------------------------------------------


def test_no_se_logean_secretos(client: TestClient) -> None:
    """Contraseña del cuerpo, token del header y query string: nada de eso sale."""
    password = "Contrasena-Super-Secreta-123"
    token = "token-secretisimo-de-supabase"

    with _capturando("json") as buffer:
        client.post(
            "/v1/auth/register?invitacion=codigo-secreto-de-invitacion",
            json={"email": "no-es-un-email", "password": password},
            headers={"Authorization": f"Bearer {token}"},
        )

    salida = buffer.getvalue()
    assert password not in salida
    assert token not in salida
    assert "codigo-secreto-de-invitacion" not in salida
    # La ruta sí, para saber qué se llamó; la query string NO (política del
    # middleware: mañana llevará búsquedas o códigos de confirmación).
    assert "/v1/auth/register" in salida
    assert "invitacion" not in salida


def test_la_traza_de_un_500_no_sale_al_cliente_pero_si_al_log(client: TestClient) -> None:
    with _capturando("json") as buffer:
        respuesta = client.get("/boom")

    assert _SECRETO_EN_LA_EXCEPCION not in respuesta.text
    assert "password-secreta" not in respuesta.text
    # En el log del servidor sí está: es donde tiene que estar para diagnosticar.
    assert _SECRETO_EN_LA_EXCEPCION in buffer.getvalue()


# --- Formato de texto para desarrollo ----------------------------------------


def test_el_formato_de_texto_sigue_siendo_legible(client: TestClient) -> None:
    with _capturando("text") as buffer:
        client.get("/v1/health")

    lineas = [linea for linea in buffer.getvalue().splitlines() if linea.strip()]
    assert lineas
    acceso = next(linea for linea in lineas if "app.access" in linea)
    assert acceso.startswith("INFO [app.access] GET /v1/health → 200")
    # El id abreviado al final, para poder seguir una petición a ojo.
    assert "(req " in acceso
    with pytest.raises(json.JSONDecodeError):
        json.loads(acceso)


# --- Config y loggers de uvicorn ---------------------------------------------


def test_el_formato_por_defecto_lo_decide_el_ambiente() -> None:
    assert Settings(_env_file=None, env="local").effective_log_format == "text"
    assert Settings(_env_file=None, env="test").effective_log_format == "text"
    produccion = Settings(
        _env_file=None,
        env="production",
        database_url="postgresql://x",
        supabase_url="https://x.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
        llm_api_key="llm",
    )
    assert produccion.effective_log_format == "json"
    # La variable dedicada manda sobre el ambiente.
    assert produccion.model_copy(update={"log_format": "text"}).effective_log_format == "text"
    assert Settings(_env_file=None, env="local", log_format="json").effective_log_format == "json"


def test_la_config_decide_el_formato_al_arrancar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin pasar ``log_format``, ``configure_logging`` lee los settings."""
    monkeypatch.setattr(settings, "log_format", "json")
    buffer = io.StringIO()
    try:
        configure_logging(stream=buffer)
        logging.getLogger("app.prueba").info("hola")
        assert json.loads(buffer.getvalue().strip())["message"] == "hola"
    finally:
        configure_logging()


def test_los_logs_de_uvicorn_salen_por_el_mismo_sitio() -> None:
    """Si no, en producción saldría texto suelto entre el JSON."""
    with _capturando("json") as buffer:
        logging.getLogger("uvicorn.error").warning("arrancando")

        assert json.loads(buffer.getvalue().strip())["logger"] == "uvicorn.error"

        # El access log de uvicorn se apaga: lo sustituye el nuestro, que
        # además trae id y duración.
        acceso = logging.getLogger("uvicorn.access")
        assert acceso.handlers == []
        assert acceso.propagate is False
