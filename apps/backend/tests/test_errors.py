"""Tests del contrato único de error y del blindaje de los 500 (HU-1.8).

Los errores de cada endpoint real se cubren en sus propios módulos; aquí se
verifica lo TRANSVERSAL: que toda familia de error tenga la misma forma, que
un fallo no previsto no filtre nada, y que el id que ve el cliente sea el
mismo que queda en el log.
"""

import io
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.errors import ApiError, ErrorCode
from app.core.logging import configure_logging
from app.main import app, create_app

# Credencial de mentira: si aparece en una respuesta, el blindaje falló.
_SECRETO = "postgresql://postgres:password-secreta@db.x.supabase.co"


@pytest.fixture
def cliente_con_rutas_de_prueba() -> Iterator[TestClient]:
    """App real + rutas que fallan a propósito (SOLO para estos tests).

    ``raise_server_exceptions=False`` hace que el TestClient devuelva la
    respuesta del handler en vez de propagar la excepción, que es justo lo que
    hace el servidor real.
    """
    app_de_prueba = create_app()

    @app_de_prueba.get("/boom")
    async def boom() -> None:
        # Excepción no prevista CON una credencial en el mensaje.
        raise RuntimeError(f"fallo interno conectando a {_SECRETO}")

    @app_de_prueba.get("/boom-api-error")
    async def boom_api_error() -> None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.CONFLICT,
            "Conflicto de prueba.",
            details={"campo": "valor"},
        )

    with TestClient(app_de_prueba, raise_server_exceptions=False) as client:
        yield client


def _error(response: Any) -> dict[str, Any]:
    """Extrae el bloque ``error`` comprobando que la forma es la del contrato."""
    cuerpo: dict[str, Any] = response.json()
    assert set(cuerpo) == {"error"}, f"cuerpo fuera del contrato: {cuerpo}"
    error: dict[str, Any] = cuerpo["error"]
    assert set(error) == {"code", "message", "details", "error_id"}
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    return error


# --- Forma común a todas las familias de error -------------------------------


def test_404_de_ruta_inexistente_sigue_el_formato(cliente_con_rutas_de_prueba: TestClient) -> None:
    """Hasta los errores que levanta el propio framework pasan por el contrato."""
    response = cliente_con_rutas_de_prueba.get("/v1/no-existe")

    assert response.status_code == 404
    error = _error(response)
    assert error["code"] == ErrorCode.NOT_FOUND
    assert error["error_id"] is None


def test_405_metodo_no_permitido_sigue_el_formato(
    cliente_con_rutas_de_prueba: TestClient,
) -> None:
    response = cliente_con_rutas_de_prueba.post("/v1/health")

    assert response.status_code == 405
    assert _error(response)["code"] == ErrorCode.METHOD_NOT_ALLOWED


def test_api_error_conserva_codigo_mensaje_y_detalles(
    cliente_con_rutas_de_prueba: TestClient,
) -> None:
    response = cliente_con_rutas_de_prueba.get("/boom-api-error")

    assert response.status_code == 409
    error = _error(response)
    assert error["code"] == ErrorCode.CONFLICT
    assert error["message"] == "Conflicto de prueba."
    assert error["details"] == {"campo": "valor"}


def test_422_de_validacion_sigue_el_formato_con_detalle_por_campo() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/auth/login", json={"email": "no-es-un-email"})

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    campos = {tuple(e["loc"]) for e in error["details"]["errors"]}
    assert ("body", "email") in campos and ("body", "password") in campos


def test_401_del_middleware_sigue_el_formato_y_conserva_www_authenticate() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/users/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    error = _error(response)
    assert error["code"] == ErrorCode.UNAUTHENTICATED
    assert error["details"] is None


def test_el_401_sigue_siendo_uniforme_dentro_del_nuevo_formato() -> None:
    """El código NO revela el motivo: es el mismo para cualquier fallo de token."""
    cabeceras = [
        {},
        {"Authorization": "Bearer no-es-un-jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer "},
    ]

    with TestClient(app) as client:
        cuerpos = [client.get("/v1/users/me", headers=h).json() for h in cabeceras]

    assert all(cuerpo == cuerpos[0] for cuerpo in cuerpos)
    assert cuerpos[0]["error"]["code"] == ErrorCode.UNAUTHENTICATED


# --- Blindaje de los 500 ------------------------------------------------------


def test_500_no_filtra_nada_y_devuelve_un_error_id(
    cliente_con_rutas_de_prueba: TestClient,
) -> None:
    response = cliente_con_rutas_de_prueba.get("/boom")

    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == ErrorCode.INTERNAL_ERROR
    assert error["details"] is None
    # Hay un identificador opaco con el que reportar el problema.
    assert isinstance(error["error_id"], str) and len(error["error_id"]) == 12
    # Y NADA de la excepción: ni el mensaje, ni el tipo, ni la traza.
    assert "RuntimeError" not in response.text
    assert "fallo interno" not in response.text
    assert "Traceback" not in response.text


def test_500_no_filtra_credenciales_del_mensaje_de_la_excepcion(
    cliente_con_rutas_de_prueba: TestClient,
) -> None:
    """La excepción lleva una URL con contraseña; el cuerpo no puede tenerla."""
    response = cliente_con_rutas_de_prueba.get("/boom")

    assert "password-secreta" not in response.text
    assert "postgresql://" not in response.text
    assert "supabase.co" not in response.text


def test_el_error_id_del_cliente_aparece_en_el_log_junto_a_la_causa(
    cliente_con_rutas_de_prueba: TestClient,
) -> None:
    """El puente entre lo que ve el usuario y lo que ve quien depura."""
    stream = io.StringIO()
    try:
        configure_logging(stream=stream)
        response = cliente_con_rutas_de_prueba.get("/boom")
    finally:
        configure_logging()

    error_id = response.json()["error"]["error_id"]
    salida = stream.getvalue()
    assert error_id in salida
    # La causa real SÍ está en el servidor: tipo, mensaje y traza.
    assert "RuntimeError" in salida
    assert "fallo interno" in salida
    assert "Traceback" in salida


def test_el_500_se_registra_a_nivel_error(
    cliente_con_rutas_de_prueba: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.core.errors"):
        cliente_con_rutas_de_prueba.get("/boom")

    # Solo los de este módulo: el log de acceso (HU-1.12) también registra la
    # petición a ERROR por ser un 5xx, y es otra línea con otro propósito.
    del_handler = [r for r in caplog.records if r.name == "app.core.errors"]
    assert [r.levelno for r in del_handler] == [logging.ERROR]
