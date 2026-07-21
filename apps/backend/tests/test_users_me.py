"""Tests de los endpoints de perfil GET/PATCH /v1/users/me — SIN Supabase real.

Se firman tokens ES256 propios y se inyecta el JWKS (tests/auth_utils.py); la
base es SQLite en fichero temporal, con cierre de engines en el teardown.
"""

import asyncio
import os
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import database
from app.main import app
from app.models import UserProfile
from tests import auth_utils

_engines_del_test: list[AsyncEngine] = []
_ficheros_del_test: list[str] = []


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    auth_utils.install_auth_env(monkeypatch)
    yield
    while _engines_del_test:
        asyncio.run(_engines_del_test.pop().dispose())
    while _ficheros_del_test:
        os.unlink(_ficheros_del_test.pop())


def _usar_sqlite(monkeypatch: pytest.MonkeyPatch) -> async_sessionmaker[AsyncSession]:
    # Fichero temporal (no :memory:): la BD sobrevive a los varios event loops.
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


def _leer_preferences(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> dict[str, object]:
    async def leer() -> dict[str, object]:
        async with factory() as session:
            perfil = await session.get(UserProfile, user_id)
            assert perfil is not None
            return dict(perfil.preferences)

    return asyncio.run(leer())


# --- GET ---------------------------------------------------------------------


def test_get_perfil_con_token_valido(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id), email="ana@example.com")

    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth(token))

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["id"] == str(user_id)
    assert cuerpo["email"] == "ana@example.com"
    assert cuerpo["plan"] == "free"
    assert cuerpo["preferences"] == {}
    assert "created_at" in cuerpo and "updated_at" in cuerpo


def test_get_perfil_sin_token_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/v1/users/me")
    assert response.status_code == 401


def test_get_perfil_token_invalido_responde_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/v1/users/me", headers=_auth("no-es-un-jwt"))
    assert response.status_code == 401


# --- PATCH: caso feliz y semántica de merge ----------------------------------


def test_patch_actualiza_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _usar_sqlite(monkeypatch)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))

    with TestClient(app) as client:
        response = client.patch(
            "/v1/users/me",
            headers=_auth(token),
            json={"preferences": {"idioma": "es", "moneda": "EUR"}},
        )

    assert response.status_code == 200
    assert response.json()["preferences"] == {"idioma": "es", "moneda": "EUR"}
    # Persistido en la base.
    assert _leer_preferences(factory, user_id) == {"idioma": "es", "moneda": "EUR"}


def test_patch_hace_merge_superficial_no_reemplazo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Merge: una clave no mencionada se conserva; una mencionada se sobrescribe."""
    _usar_sqlite(monkeypatch)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))

    with TestClient(app) as client:
        client.patch(
            "/v1/users/me",
            headers=_auth(token),
            json={"preferences": {"idioma": "es", "moneda": "EUR"}},
        )
        response = client.patch(
            "/v1/users/me",
            headers=_auth(token),
            json={"preferences": {"moneda": "USD"}},
        )

    # 'idioma' se conserva (merge), 'moneda' se sobrescribe.
    assert response.json()["preferences"] == {"idioma": "es", "moneda": "USD"}


def test_patch_actualiza_updated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    """updated_at refleja el cambio (onupdate de la base)."""
    factory = _usar_sqlite(monkeypatch)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))

    with TestClient(app) as client:
        # Primera petición: crea el perfil (created_at ≈ updated_at ≈ ahora).
        client.get("/v1/users/me", headers=_auth(token))

        # Se envejece updated_at a una fecha lejana para detectar sin ambigüedad
        # que el PATCH la mueve (SQLite CURRENT_TIMESTAMP tiene resolución de
        # segundos; sin envejecer, el cambio podría caer en el mismo segundo).
        async def envejecer() -> None:
            async with factory() as session:
                await session.execute(
                    update(UserProfile)
                    .where(UserProfile.id == user_id)
                    .values(updated_at=datetime(2000, 1, 1, tzinfo=UTC))
                )
                await session.commit()

        asyncio.run(envejecer())

        response = client.patch(
            "/v1/users/me", headers=_auth(token), json={"preferences": {"x": 1}}
        )

    assert response.status_code == 200
    assert not response.json()["updated_at"].startswith("2000")


# --- PATCH: rechazos ---------------------------------------------------------


@pytest.mark.parametrize("campo_extra", ["plan", "email", "id"])
def test_patch_campo_desconocido_responde_422_sin_cambiar_el_perfil(
    monkeypatch: pytest.MonkeyPatch, campo_extra: str
) -> None:
    """Un intento de tocar plan/email/id → 422, y el perfil NO cambia."""
    factory = _usar_sqlite(monkeypatch)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))

    with TestClient(app) as client:
        client.get("/v1/users/me", headers=_auth(token))  # crea el perfil
        response = client.patch(
            "/v1/users/me",
            headers=_auth(token),
            json={"preferences": {"idioma": "es"}, campo_extra: "pro"},
        )

    assert response.status_code == 422
    # Nada se aplicó: preferences sigue vacío (ni siquiera el 'idioma' válido).
    assert _leer_preferences(factory, user_id) == {}


@pytest.mark.parametrize("valor", [[1, 2], "texto", 5, True])
def test_patch_preferences_no_objeto_responde_422(
    monkeypatch: pytest.MonkeyPatch, valor: object
) -> None:
    _usar_sqlite(monkeypatch)
    token = auth_utils.make_token(sub=str(uuid.uuid4()))
    with TestClient(app) as client:
        response = client.patch("/v1/users/me", headers=_auth(token), json={"preferences": valor})
    assert response.status_code == 422


def test_patch_preferences_demasiado_grande_responde_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar_sqlite(monkeypatch)
    token = auth_utils.make_token(sub=str(uuid.uuid4()))
    enorme = {"blob": "x" * 9000}  # supera el tope de 8192 bytes
    with TestClient(app) as client:
        response = client.patch("/v1/users/me", headers=_auth(token), json={"preferences": enorme})
    assert response.status_code == 422


# --- Aislamiento entre usuarios ----------------------------------------------


def test_un_usuario_no_ve_ni_toca_el_perfil_de_otro(monkeypatch: pytest.MonkeyPatch) -> None:
    """El id sale del token, nunca del cuerpo ni de la URL: cada uno ve el suyo."""
    factory = _usar_sqlite(monkeypatch)
    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    token_a = auth_utils.make_token(sub=str(id_a), email="a@example.com")
    token_b = auth_utils.make_token(sub=str(id_b), email="b@example.com")

    with TestClient(app) as client:
        # A modifica SUS preferencias.
        client.patch("/v1/users/me", headers=_auth(token_a), json={"preferences": {"idioma": "es"}})
        # B lee: ve su propio perfil (email B, preferencias vacías), no el de A.
        perfil_b = client.get("/v1/users/me", headers=_auth(token_b)).json()

    assert perfil_b["id"] == str(id_b)
    assert perfil_b["email"] == "b@example.com"
    assert perfil_b["preferences"] == {}
    # El perfil de A conserva su cambio, intacto.
    assert _leer_preferences(factory, id_a) == {"idioma": "es"}
