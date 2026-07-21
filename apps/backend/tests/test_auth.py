"""Tests de POST /v1/auth/register — SIN Supabase real (CI sin credenciales).

Supabase Auth se sustituye monkeypatcheando ``app.services.auth.sign_up``; la
base de datos se sustituye por SQLite async en memoria con el esquema de
``Base.metadata`` ya creado (mismo patrón que ``test_database.py`` y
``test_models.py``).
"""

import asyncio
import io
import logging
import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import database
from app.core.config import settings
from app.core.logging import configure_logging
from app.main import app
from app.models import UserProfile
from app.services import auth as auth_service

_EMAIL = "viajera@example.com"
_PASSWORD = "una-contrasena-larga-y-segura"


def _sqlite_factory_con_esquema() -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones SQLite en memoria, con ``user_profiles`` ya creada."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def crear_esquema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)

    asyncio.run(crear_esquema())
    return async_sessionmaker(engine, expire_on_commit=False)


def _mock_sign_up(
    monkeypatch: pytest.MonkeyPatch, *, user_id: uuid.UUID | None = None, con_sesion: bool = True
) -> uuid.UUID:
    """Reemplaza ``sign_up`` por un éxito fijo (con o sin sesión); devuelve el id."""
    resuelto_id = user_id or uuid.uuid4()

    async def fake_sign_up(email: str, password: str) -> auth_service.SignUpResult:
        session = (
            auth_service.SupabaseSession(
                access_token="access-de-prueba", refresh_token="refresh-de-prueba"
            )
            if con_sesion
            else None
        )
        return auth_service.SignUpResult(user_id=str(resuelto_id), email=email, session=session)

    monkeypatch.setattr(auth_service, "sign_up", fake_sign_up)
    return resuelto_id


def _mock_sign_up_exitoso(
    monkeypatch: pytest.MonkeyPatch, *, user_id: uuid.UUID | None = None
) -> uuid.UUID:
    """Alta CON sesión (confirmación de email desactivada)."""
    return _mock_sign_up(monkeypatch, user_id=user_id, con_sesion=True)


def _mock_sign_up_error(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    async def fake_sign_up(email: str, password: str) -> auth_service.SignUpResult:
        raise error

    monkeypatch.setattr(auth_service, "sign_up", fake_sign_up)


def _leer_perfil(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> UserProfile:
    async def consulta() -> UserProfile:
        async with factory() as session:
            return (
                await session.execute(select(UserProfile).where(UserProfile.id == user_id))
            ).scalar_one()

    return asyncio.run(consulta())


def test_registro_con_confirmacion_desactivada_devuelve_sesion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alta CON sesión: 201, status 'active', sesión presente, perfil creado."""
    factory = _sqlite_factory_con_esquema()
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    user_id = _mock_sign_up(monkeypatch, con_sesion=True)

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 201
    assert response.json() == {
        "status": "active",
        "user": {"id": str(user_id), "email": _EMAIL},
        "session": {
            "access_token": "access-de-prueba",
            "refresh_token": "refresh-de-prueba",
            "token_type": "bearer",
        },
    }

    perfil = _leer_perfil(factory, user_id)
    assert perfil.email == _EMAIL
    assert perfil.plan.value == "free"


def test_registro_con_confirmacion_pendiente_no_devuelve_sesion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alta SIN sesión: 201 (no 503), status pendiente, sin sesión, perfil creado."""
    factory = _sqlite_factory_con_esquema()
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    user_id = _mock_sign_up(monkeypatch, con_sesion=False)

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 201
    assert response.json() == {
        "status": "pending_email_confirmation",
        "user": {"id": str(user_id), "email": _EMAIL},
        "session": None,
    }

    # El perfil se crea igual que en el caso con sesión.
    perfil = _leer_perfil(factory, user_id)
    assert perfil.email == _EMAIL
    assert perfil.plan.value == "free"


def test_la_respuesta_no_filtra_la_contrasena(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _sqlite_factory_con_esquema()
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    _mock_sign_up_exitoso(monkeypatch)

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert _PASSWORD not in response.text


def test_email_duplicado_responde_409_sin_revelar_de_mas(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_sign_up_error(monkeypatch, auth_service.EmailAlreadyExists("detalle interno de Supabase"))

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 409
    assert response.json() == {"detail": "Ya existe una cuenta con ese email."}


def test_contrasena_rechazada_por_supabase_responde_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_sign_up_error(monkeypatch, auth_service.WeakPassword("no cumple la política"))

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 422


def test_email_rechazado_por_supabase_responde_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_sign_up_error(monkeypatch, auth_service.InvalidEmail("no es válido"))

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 422


def test_password_corta_responde_422_sin_llegar_a_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La validación local (longitud mínima) corta antes de tocar Supabase."""
    llamado = False

    async def fake_sign_up(email: str, password: str) -> auth_service.SupabaseSession:
        nonlocal llamado
        llamado = True
        raise AssertionError("no debería llamarse: la validación local ya debió cortar")

    monkeypatch.setattr(auth_service, "sign_up", fake_sign_up)

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": "corta"})

    assert response.status_code == 422
    assert not llamado


def test_email_con_formato_invalido_responde_422_sin_llegar_a_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamado = False

    async def fake_sign_up(email: str, password: str) -> auth_service.SupabaseSession:
        nonlocal llamado
        llamado = True
        raise AssertionError("no debería llamarse: la validación local ya debió cortar")

    monkeypatch.setattr(auth_service, "sign_up", fake_sign_up)

    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/register", json={"email": "no-es-un-email", "password": _PASSWORD}
        )

    assert response.status_code == 422
    assert not llamado


def test_fallo_del_proveedor_responde_503_sin_filtrar_detalles_internos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_sign_up_error(
        monkeypatch, auth_service.AuthProviderError("timeout contra api-key=secreta-interna")
    )

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 503
    assert "secreta-interna" not in response.text


def test_fallo_al_crear_el_perfil_local_no_rompe_el_registro(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """El alta en Supabase ya tuvo éxito: el registro debe seguir devolviendo 201."""

    def factory_rota() -> async_sessionmaker[AsyncSession]:
        raise RuntimeError("la base está caída")

    monkeypatch.setattr(database, "get_session_factory", factory_rota)
    user_id = _mock_sign_up_exitoso(monkeypatch)

    with caplog.at_level("ERROR"):
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD}
            )

    assert response.status_code == 201
    assert response.json()["user"]["id"] == str(user_id)
    assert "perfil local" in caplog.text.lower()


def test_rate_limit_de_supabase_responde_429(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Un RateLimited del servicio se mapea a 429 (no a 422 ni 503) y se loguea."""
    _mock_sign_up_error(
        monkeypatch,
        auth_service.RateLimited(
            "Demasiados intentos; prueba de nuevo en unos minutos.",
            provider_status=429,
            provider_error_code="over_email_send_rate_limit",
            provider_message="email rate limit exceeded",
        ),
    )

    with caplog.at_level("WARNING"):
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD}
            )

    assert response.status_code == 429
    # El servidor deja rastro de la causa real (status + error_code), sin secretos.
    assert "over_email_send_rate_limit" in caplog.text
    assert _PASSWORD not in caplog.text


def test_los_logs_de_fallo_no_incluyen_la_contrasena(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """El diagnóstico del proveedor va al log; la contraseña y las llaves nunca."""
    _mock_sign_up_error(
        monkeypatch,
        auth_service.AuthProviderError(
            "Supabase Auth rechazó la solicitud.",
            provider_status=500,
            provider_error_code="unexpected_failure",
            provider_message="internal error",
        ),
    )

    with caplog.at_level("ERROR"):
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD}
            )

    assert response.status_code == 503
    assert "unexpected_failure" in caplog.text
    assert _PASSWORD not in caplog.text


def test_contrasena_corta_no_aparece_en_el_cuerpo_del_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug 3: la contraseña rechazada por longitud NO debe viajar en la respuesta."""
    # sign_up no debe llegar a llamarse; si lo hace, que sea evidente.
    _mock_sign_up_exitoso(monkeypatch)

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": "abc123"})

    assert response.status_code == 422
    assert "abc123" not in response.text
    # El resto del error de validación se conserva (tipo y ubicación del campo).
    detalle = response.json()["detail"][0]
    assert detalle["loc"][-1] == "password"
    assert "input" not in detalle


# --- Traducción de errores del proveedor (unidad, sin HTTP) ------------------


def test_translate_error_mapea_por_error_code_no_por_texto() -> None:
    """La regresión del Bug 1: un 429 con 'email...' NO debe caer en InvalidEmail."""
    exc = auth_service._translate_error(
        {"error_code": "over_email_send_rate_limit", "msg": "email rate limit exceeded"},
        429,
    )

    assert isinstance(exc, auth_service.RateLimited)
    assert exc.provider_error_code == "over_email_send_rate_limit"


def test_translate_error_email_duplicado_y_password_debil_por_codigo() -> None:
    duplicado = auth_service._translate_error(
        {"error_code": "email_exists", "msg": "cualquier texto"}, 422
    )
    otro_duplicado = auth_service._translate_error({"error_code": "user_already_exists"}, 422)
    password = auth_service._translate_error({"error_code": "weak_password"}, 422)
    email = auth_service._translate_error({"error_code": "email_address_invalid"}, 400)

    assert isinstance(duplicado, auth_service.EmailAlreadyExists)
    assert isinstance(otro_duplicado, auth_service.EmailAlreadyExists)
    assert isinstance(password, auth_service.WeakPassword)
    assert isinstance(email, auth_service.InvalidEmail)


def test_translate_error_codigo_desconocido_cae_en_provider_error() -> None:
    """Sin error_code reconocible NO se adivina por el texto: AuthProviderError."""
    exc = auth_service._translate_error(
        {"error_code": "algo_nuevo_de_supabase", "msg": "password looks weak to me"},
        400,
    )

    assert type(exc) is auth_service.AuthProviderError
    # El error_code se conserva para los logs, aunque no se muestre al cliente.
    assert exc.provider_error_code == "algo_nuevo_de_supabase"


def test_translate_error_429_sin_codigo_conocido_es_rate_limited() -> None:
    """El status 429 basta para RateLimited aunque no haya error_code mapeado."""
    exc = auth_service._translate_error({"msg": "too many requests"}, 429)

    assert isinstance(exc, auth_service.RateLimited)


# --- Parseo del 2xx de signup: con sesión, sin sesión, e incoherente ---------


def test_parse_signup_con_tokens_devuelve_sesion() -> None:
    result = auth_service._parse_signup(
        {
            "user": {"id": "abc", "email": "a@b.com"},
            "access_token": "at",
            "refresh_token": "rt",
        }
    )

    assert result.user_id == "abc"
    assert result.session is not None
    assert result.session.access_token == "at"


def test_parse_signup_sin_tokens_es_confirmacion_pendiente() -> None:
    """Usuario presente y sin tokens NO es error: es confirmación pendiente."""
    result = auth_service._parse_signup({"user": {"id": "abc", "email": "a@b.com"}})

    assert result.user_id == "abc"
    assert result.session is None


def test_parse_signup_sin_usuario_es_provider_error() -> None:
    """Respuesta genuinamente incoherente (sin usuario) → AuthProviderError."""
    with pytest.raises(auth_service.AuthProviderError):
        auth_service._parse_signup({"access_token": "at", "refresh_token": "rt"})


def test_parse_signup_con_un_solo_token_es_provider_error() -> None:
    """Un token sí y el otro no es incoherente, no un estado del negocio."""
    with pytest.raises(auth_service.AuthProviderError):
        auth_service._parse_signup(
            {"user": {"id": "abc", "email": "a@b.com"}, "access_token": "at"}
        )


# Cuerpo real de GoTrue cuando "Confirm email" está ACTIVADO: el usuario va en
# la RAÍZ (sin clave "user" ni tokens). Claves verificadas contra Supabase.
_CUERPO_RAIZ_SIN_SESION = {
    "id": "d1e2f3a4-0000-0000-0000-000000000000",
    "aud": "authenticated",
    "role": "authenticated",
    "email": "viajera@example.com",
    "phone": "",
    "confirmation_sent_at": "2026-07-21T10:00:00Z",
    "app_metadata": {"provider": "email", "providers": ["email"]},
    "user_metadata": {},
    "identities": [],
    "created_at": "2026-07-21T10:00:00Z",
    "updated_at": "2026-07-21T10:00:00Z",
    "is_anonymous": False,
}


def test_parse_signup_formato_raiz_es_confirmacion_pendiente() -> None:
    """Usuario en la RAÍZ (sin 'user' ni tokens) → resultado sin sesión (pending)."""
    result = auth_service._parse_signup(_CUERPO_RAIZ_SIN_SESION)

    assert result.user_id == "d1e2f3a4-0000-0000-0000-000000000000"
    assert result.email == "viajera@example.com"
    assert result.session is None


def test_parse_signup_user_presente_pero_invalido_no_cae_al_respaldo() -> None:
    """Si 'user' está pero es inválido, NO se usa la raíz: es incoherente."""
    with pytest.raises(auth_service.AuthProviderError):
        auth_service._parse_signup({"user": {"id": 123}, "id": "raiz", "email": "raiz@example.com"})


def test_respuesta_incoherente_del_proveedor_responde_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si sign_up lanza AuthProviderError por forma inesperada, el endpoint da 503."""
    _mock_sign_up_error(
        monkeypatch, auth_service.AuthProviderError("Respuesta de Supabase Auth sin usuario.")
    )

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 503


# --- End-to-end del registro a través del sign_up REAL, con httpx mockeado ---


class _FakeResponse:
    """Respuesta httpx mínima: status + .json() (sin red)."""

    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def _mock_signup_http(monkeypatch: pytest.MonkeyPatch, status_code: int, payload: Any) -> None:
    """Hace que ``sign_up`` reciba (status_code, payload) sin tocar la red.

    Sustituye ``httpx.AsyncClient`` por un doble que devuelve la respuesta dada
    en ``.post`` y configura las credenciales mínimas de Supabase.
    """
    # settings es un único objeto compartido: auth._require_configured lee el
    # mismo, así que basta parchear sus atributos aquí.
    monkeypatch.setattr(settings, "supabase_url", "https://proyecto.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", SecretStr("anon-de-prueba"))

    response = _FakeResponse(status_code, payload)

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            return response

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


def test_e2e_formato_raiz_devuelve_201_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug 1: cuerpo 200 en formato RAÍZ → 201 pending_email_confirmation (no 503)."""
    factory = _sqlite_factory_con_esquema()
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    user_id = uuid.uuid4()
    payload = {
        "id": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "email": _EMAIL,
        "app_metadata": {"provider": "email"},
        "user_metadata": {},
        "identities": [],
        "created_at": "2026-07-21T10:00:00Z",
        "updated_at": "2026-07-21T10:00:00Z",
        "is_anonymous": False,
    }
    _mock_signup_http(monkeypatch, 200, payload)

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 201
    assert response.json() == {
        "status": "pending_email_confirmation",
        "user": {"id": str(user_id), "email": _EMAIL},
        "session": None,
    }
    # El perfil se crea igual en el caso pendiente.
    perfil = _leer_perfil(factory, user_id)
    assert perfil.email == _EMAIL


def test_e2e_formato_anidado_devuelve_201_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """El formato ANIDADO (con 'user' y ambos tokens) sigue dando active con sesión."""
    factory = _sqlite_factory_con_esquema()
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    user_id = uuid.uuid4()
    payload = {
        "access_token": "at-real",
        "refresh_token": "rt-real",
        "token_type": "bearer",
        "user": {"id": str(user_id), "email": _EMAIL, "role": "authenticated"},
    }
    _mock_signup_http(monkeypatch, 200, payload)

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 201
    cuerpo = response.json()
    assert cuerpo["status"] == "active"
    assert cuerpo["session"]["access_token"] == "at-real"
    assert cuerpo["user"]["id"] == str(user_id)


def test_e2e_cuerpo_sin_usuario_identificable_es_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un 200 sin usuario en ninguna forma sigue siendo incoherente → 503."""
    _mock_signup_http(monkeypatch, 200, {"algo": "inesperado"})

    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 503


# --- Logging: los fallos deben EMITIRSE de verdad, no solo llamar al logger ---


def test_configure_logging_emite_mensajes_de_la_app_por_su_stream() -> None:
    """Prueba efectiva: un log de un logger app.* llega al stream configurado."""
    stream = io.StringIO()
    try:
        configure_logging(stream=stream)
        logging.getLogger("app.servicio.prueba").error("linea-visible-xyz")
    finally:
        configure_logging()  # restaura la salida estándar para el resto de tests

    salida = stream.getvalue()
    assert "linea-visible-xyz" in salida
    assert "ERROR" in salida
    assert "[app.servicio.prueba]" in salida


def test_fallo_del_proveedor_emite_una_linea_con_status_y_codigo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El 503 produce una línea REAL en la salida con status + error_code, sin secretos."""
    _mock_sign_up_error(
        monkeypatch,
        auth_service.AuthProviderError(
            "Supabase Auth rechazó la solicitud.",
            provider_status=500,
            provider_error_code="unexpected_failure",
            provider_message="internal error",
        ),
    )
    stream = io.StringIO()
    try:
        configure_logging(stream=stream)
        with TestClient(app) as client:
            response = client.post(
                "/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD}
            )
    finally:
        configure_logging()

    assert response.status_code == 503
    salida = stream.getvalue()
    assert "unexpected_failure" in salida
    assert "status=500" in salida
    assert _PASSWORD not in salida
    assert "anon" not in salida.lower()


def test_idempotencia_el_mismo_id_no_duplica_ni_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registrar dos veces con el mismo id de Supabase no rompe ni duplica la fila."""
    factory = _sqlite_factory_con_esquema()
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    user_id = uuid.uuid4()
    _mock_sign_up_exitoso(monkeypatch, user_id=user_id)

    with TestClient(app) as client:
        primera = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})
        segunda = client.post("/v1/auth/register", json={"email": _EMAIL, "password": _PASSWORD})

    assert primera.status_code == 201
    assert segunda.status_code == 201

    async def contar_filas() -> int:
        async with factory() as session:
            filas = (
                (await session.execute(select(UserProfile).where(UserProfile.id == user_id)))
                .scalars()
                .all()
            )
            return len(filas)

    assert asyncio.run(contar_filas()) == 1
