"""Tests del middleware de auth (``get_current_user``, HU-1.6) — SIN Supabase real.

Se ejercen a través de ``GET /v1/users/me``, una ruta protegida REAL: hasta la
HU-1.9 existía ``GET /v1/auth/me`` solo para verificar el middleware, y al
consolidarse en ``/v1/users/me`` estos tests apuntan ahí. Lo que se comprueba
no es el endpoint (eso es test_users_me.py) sino la dependencia: motivos de
rechazo, uniformidad del 401 y creación perezosa del perfil.

Se generan pares de claves ES256 de prueba y se firman tokens en el propio
test; el JWKS se inyecta parcheando ``app.core.security._fetch_jwks``, sin
tocar el JWKS real. La base es SQLite async en fichero temporal.
"""

import asyncio
import io
import json
import os
import tempfile
import time
import uuid
from collections.abc import Iterator

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.core import database, security
from app.core.config import settings
from app.core.logging import configure_logging
from app.main import app
from app.models import UserProfile

_SUPABASE_URL = "https://test-project.supabase.co"
_ISSUER = f"{_SUPABASE_URL}/auth/v1"
_AUDIENCE = "authenticated"
_KID = "test-kid"

# Par de claves ES256 de prueba (uno "bueno" y otro "impostor" para firmas
# inválidas), generados una vez para todo el módulo.
_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
_IMPOSTOR_KEY = ec.generate_private_key(ec.SECP256R1())


def _jwks_de(*keys: tuple[str, ec.EllipticCurvePrivateKey]) -> jwt.PyJWKSet:
    """Construye un PyJWKSet con las claves PÚBLICAS dadas (kid, key)."""
    jwks_keys = []
    for kid, private in keys:
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
        jwk.update({"kid": kid, "alg": "ES256", "use": "sig"})
        jwks_keys.append(jwk)
    return jwt.PyJWKSet.from_dict({"keys": jwks_keys})


def _token(
    *,
    sub: str | None = None,
    email: str | None = "viajera@example.com",
    iss: str = _ISSUER,
    aud: str = _AUDIENCE,
    exp_delta: int = 3600,
    kid: str = _KID,
    key: ec.EllipticCurvePrivateKey = _PRIVATE_KEY,
    include_exp: bool = True,
) -> str:
    """Firma un JWT ES256 de prueba con los claims dados."""
    payload: dict[str, object] = {"iss": iss, "aud": aud}
    if sub is not None:
        payload["sub"] = sub
    if email is not None:
        payload["email"] = email
    if include_exp:
        payload["exp"] = int(time.time()) + exp_delta
    return jwt.encode(payload, key, algorithm="ES256", headers={"kid": kid})


# Recursos creados por _usar_sqlite en el test actual, para limpiarlos al final.
_engines_del_test: list[AsyncEngine] = []
_ficheros_del_test: list[str] = []


@pytest.fixture(autouse=True)
def _entorno_auth(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configura la URL de Supabase, inyecta el JWKS de prueba y aísla la caché.

    Al terminar, cierra los engines y borra los ficheros SQLite del test.
    """
    monkeypatch.setattr(settings, "supabase_url", _SUPABASE_URL)

    async def fake_fetch() -> jwt.PyJWKSet:
        return _jwks_de((_KID, _PRIVATE_KEY))

    monkeypatch.setattr(security, "_fetch_jwks", fake_fetch)
    security.reset_jwks_cache()
    yield
    security.reset_jwks_cache()
    while _engines_del_test:
        asyncio.run(_engines_del_test.pop().dispose())
    while _ficheros_del_test:
        os.unlink(_ficheros_del_test.pop())


def _usar_sqlite(monkeypatch: pytest.MonkeyPatch) -> async_sessionmaker[AsyncSession]:
    # Fichero temporal (no :memory:): el esquema y los datos quedan en disco, así
    # cualquier conexión —desde el schema, el TestClient o el conteo, cada uno en
    # su event loop— ve la misma BD. Robusto frente a reconexiones del pool.
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    _ficheros_del_test.append(path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    async def crear() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)

    asyncio.run(crear())
    _engines_del_test.append(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    return factory


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _contar_perfiles(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> int:
    async def contar() -> int:
        async with factory() as session:
            filas = (
                (await session.execute(select(UserProfile).where(UserProfile.id == user_id)))
                .scalars()
                .all()
            )
            return len(filas)

    return asyncio.run(contar())


# --- Caso feliz + creación perezosa ------------------------------------------


def test_token_valido_devuelve_identidad_y_crea_el_perfil(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _usar_sqlite(monkeypatch)
    user_id = uuid.uuid4()
    token = _token(sub=str(user_id), email="ana@example.com")

    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth(token))

    assert response.status_code == 200
    # La identidad resuelta por el middleware (el resto del perfil lo cubre
    # test_users_me.py; aquí solo importa a QUIÉN resolvió el token).
    cuerpo = response.json()
    assert (cuerpo["id"], cuerpo["email"], cuerpo["plan"]) == (
        str(user_id),
        "ana@example.com",
        "free",
    )
    # Creación perezosa: el perfil no existía y el middleware lo materializó.
    assert _contar_perfiles(factory, user_id) == 1


def test_perfil_existente_se_reutiliza_sin_duplicar(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _usar_sqlite(monkeypatch)
    user_id = uuid.uuid4()
    token = _token(sub=str(user_id))

    with TestClient(app) as client:
        primera = client.get("/v1/users/me", headers=_auth(token))
        segunda = client.get("/v1/users/me", headers=_auth(token))

    assert primera.status_code == 200
    assert segunda.status_code == 200
    assert _contar_perfiles(factory, user_id) == 1


def test_creacion_perezosa_carrera_integrityerror_relee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si el perfil ya existe cuando el middleware intenta insertarlo (carrera),
    el IntegrityError no rompe: relee y devuelve la fila existente.

    Test unitario de ``_resolve_or_create_profile`` en un ÚNICO event loop (la
    conexión :memory: compartida no tolera writes desde varios loops).
    """
    user_id = uuid.uuid4()

    async def escenario() -> tuple[str, int]:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(database, "get_session_factory", lambda: factory)

        # Otra petición ya insertó el perfil (fila competidora).
        async with factory() as session:
            session.add(UserProfile(id=user_id, email="otra@example.com"))
            await session.commit()

        # Forzar la carrera: el PRIMER get devuelve None (como si el perfil aún
        # no existiera), así se intenta insertar y choca con la PK presente
        # (IntegrityError); el segundo get relee la fila real.
        original_get = AsyncSession.get
        llamadas = {"n": 0}

        async def get_primero_none(self: AsyncSession, *args: object, **kwargs: object) -> object:
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                return None
            return await original_get(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(AsyncSession, "get", get_primero_none)

        profile = await deps._resolve_or_create_profile(user_id=user_id, email="ana@example.com")

        # El conteo usa execute(select(...)), no get, así que el patch de get
        # (ya en su 2ª llamada = real) no lo afecta.
        async with factory() as session:
            filas = (
                (await session.execute(select(UserProfile).where(UserProfile.id == user_id)))
                .scalars()
                .all()
            )
        await engine.dispose()
        return profile.email, len(filas)

    email, n_filas = asyncio.run(escenario())

    # Devuelve el perfil existente (el precreado), sin romper ni duplicar.
    assert email == "otra@example.com"
    assert n_filas == 1


# --- Rechazos: todos 401 con cuerpo idéntico ---------------------------------


def _get_me(client: TestClient, headers: dict[str, str]) -> object:
    return client.get("/v1/users/me", headers=headers)


def test_sin_header_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/v1/users/me")
    assert response.status_code == 401


def test_esquema_incorrecto_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    token = _token(sub=str(uuid.uuid4()))
    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers={"Authorization": f"Basic {token}"})
    assert response.status_code == 401


def test_token_malformado_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth("esto-no-es-un-jwt"))
    assert response.status_code == 401


def test_firma_invalida_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token firmado con una clave que NO está en el JWKS (impostor)."""
    _usar_sqlite(monkeypatch)
    token = _token(sub=str(uuid.uuid4()), key=_IMPOSTOR_KEY)  # mismo kid, otra clave
    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth(token))
    assert response.status_code == 401


def test_token_expirado_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    token = _token(sub=str(uuid.uuid4()), exp_delta=-10)
    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth(token))
    assert response.status_code == 401


def test_issuer_incorrecto_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    token = _token(sub=str(uuid.uuid4()), iss="https://otro-proyecto.supabase.co/auth/v1")
    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth(token))
    assert response.status_code == 401


def test_audiencia_incorrecta_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    token = _token(sub=str(uuid.uuid4()), aud="otra-audiencia")
    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth(token))
    assert response.status_code == 401


def test_kid_desconocido_responde_401_tras_refrescar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un kid ausente del JWKS fuerza un refresco; si sigue sin estar → 401."""
    _usar_sqlite(monkeypatch)
    refrescos = 0
    original = security._fetch_jwks

    async def contar_fetch() -> jwt.PyJWKSet:
        nonlocal refrescos
        refrescos += 1
        return await original()

    monkeypatch.setattr(security, "_fetch_jwks", contar_fetch)
    security.reset_jwks_cache()
    token = _token(sub=str(uuid.uuid4()), kid="kid-que-no-existe")

    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth(token))

    assert response.status_code == 401
    # Se intentó traer el JWKS al menos dos veces (carga inicial + refresco).
    assert refrescos >= 2


def test_todos_los_401_tienen_el_mismo_cuerpo(monkeypatch: pytest.MonkeyPatch) -> None:
    """El cliente no puede distinguir el motivo: el 401 es uniforme."""
    _usar_sqlite(monkeypatch)
    uid = str(uuid.uuid4())
    tokens = {
        "sin_header": None,
        "expirado": _token(sub=uid, exp_delta=-10),
        "firma": _token(sub=uid, key=_IMPOSTOR_KEY),
        "issuer": _token(sub=uid, iss="https://malo.supabase.co/auth/v1"),
        "audiencia": _token(sub=uid, aud="mala"),
        "malformado": "no-jwt",
    }

    cuerpos = []
    with TestClient(app) as client:
        for token in tokens.values():
            headers = _auth(token) if token is not None else {}
            r = client.get("/v1/users/me", headers=headers)
            assert r.status_code == 401
            cuerpos.append(r.json())

    assert all(cuerpo == cuerpos[0] for cuerpo in cuerpos)


def test_el_motivo_real_del_401_aparece_en_los_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """El cuerpo es genérico, pero el log SÍ dice por qué falló (aquí: expirado)."""
    _usar_sqlite(monkeypatch)
    token = _token(sub=str(uuid.uuid4()), exp_delta=-10)

    stream = io.StringIO()
    try:
        configure_logging(stream=stream)
        with TestClient(app) as client:
            response = client.get("/v1/users/me", headers=_auth(token))
    finally:
        configure_logging()

    assert response.status_code == 401
    salida = stream.getvalue()
    assert "expired" in salida
    assert token not in salida  # el token no se loguea
