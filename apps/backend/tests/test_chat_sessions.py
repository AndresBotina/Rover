"""Tests de `/v1/chat/sessions` — listar, leer y borrar conversaciones (HU-2.5).

Dos propiedades concentran casi todo el módulo, y ninguna se ve mirando un 200:

1. **Nada ajeno se filtra ni se insinúa.** Las conversaciones de otra persona,
   las inexistentes y las borradas responden lo mismo byte a byte.
2. **Los ``tool_steps`` no salen nunca.** Se comprueba contra una conversación
   que SÍ los tiene guardados, con una frase señuelo dentro: si aparece en el
   cuerpo, el test se pone rojo.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.config import settings
from app.main import app
from app.models import Conversation, Message, MessageRole, UserProfile
from app.services.llm import set_llm_provider
from tests import auth_utils
from tests.conftest import BaseDeTest
from tests.test_chat import ProveedorDeChat, eventos_de

SESIONES = "/v1/chat/sessions"

#: Si esta frase aparece en una respuesta de la API, algo filtró los pasos
#: internos de tool-calling.
SEÑUELO = "SECRETO-DE-LA-HERRAMIENTA"


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_utils.install_auth_env(monkeypatch)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _usuario() -> tuple[uuid.UUID, str]:
    uid = uuid.uuid4()
    return uid, auth_utils.make_token(sub=str(uid))


def _crear(
    bd: BaseDeTest,
    *,
    user_id: uuid.UUID,
    titulo: str,
    mensajes: list[tuple[MessageRole, str]] | None = None,
    tool_steps: list[dict[str, object]] | None = None,
    borrada: bool = False,
    actividad: datetime | None = None,
    crear_perfil: bool = True,
) -> uuid.UUID:
    """Conversación ya escrita, como la dejaría un turno anterior."""
    conversation_id = uuid.uuid4()

    async def escribir() -> None:
        async with bd.factory() as session:
            if crear_perfil:
                session.add(UserProfile(id=user_id, email=f"{user_id}@example.com"))
                await session.flush()
            session.add(
                Conversation(
                    id=conversation_id,
                    user_id=user_id,
                    title=titulo,
                    deleted_at=datetime.now(UTC) if borrada else None,
                )
            )
            await session.flush()
            for i, (role, content) in enumerate(mensajes or []):
                session.add(
                    Message(
                        conversation_id=conversation_id,
                        role=role,
                        sequence=i,
                        content=content,
                        tool_steps=tool_steps or [],
                    )
                )
            if actividad is not None:
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(updated_at=actividad)
                )
            await session.commit()

    bd.run(escribir)
    return conversation_id


def _leer_conversacion(bd: BaseDeTest, conversation_id: uuid.UUID) -> Conversation:
    async def leer() -> Conversation:
        async with bd.factory() as session:
            fila = await session.get(Conversation, conversation_id)
            assert fila is not None
            return fila

    return bd.run(leer)


# --- GET /v1/chat/sessions ---------------------------------------------------


def test_lista_solo_las_conversaciones_vivas_del_usuario(bd: BaseDeTest) -> None:
    user_id, token = _usuario()
    mia = _crear(bd, user_id=user_id, titulo="Mía")
    _crear(bd, user_id=user_id, titulo="Borrada", borrada=True, crear_perfil=False)
    _crear(bd, user_id=uuid.uuid4(), titulo="De otra persona")

    with TestClient(app) as client:
        respuesta = client.get(SESIONES, headers=_auth(token))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [item["id"] for item in cuerpo["items"]] == [str(mia)]
    assert cuerpo["items"][0]["title"] == "Mía"
    assert cuerpo["limit"] == 50
    # La cabecera, no el historial: pintar una barra lateral no debe
    # descargarse todas las conversaciones de la cuenta.
    assert set(cuerpo["items"][0]) == {"id", "title", "created_at", "updated_at"}


def test_la_lista_ordena_por_actividad_reciente(bd: BaseDeTest) -> None:
    user_id, token = _usuario()
    ahora = datetime.now(UTC)
    vieja = _crear(bd, user_id=user_id, titulo="Vieja", actividad=ahora - timedelta(days=3))
    reciente = _crear(
        bd,
        user_id=user_id,
        titulo="Reciente",
        actividad=ahora - timedelta(minutes=1),
        crear_perfil=False,
    )
    media = _crear(
        bd,
        user_id=user_id,
        titulo="Media",
        actividad=ahora - timedelta(hours=5),
        crear_perfil=False,
    )

    with TestClient(app) as client:
        cuerpo = client.get(SESIONES, headers=_auth(token)).json()

    assert [item["id"] for item in cuerpo["items"]] == [str(reciente), str(media), str(vieja)]


def test_el_limite_acota_y_se_puede_pedir(bd: BaseDeTest) -> None:
    user_id, token = _usuario()
    ahora = datetime.now(UTC)
    for i in range(4):
        _crear(
            bd,
            user_id=user_id,
            titulo=f"C{i}",
            actividad=ahora - timedelta(minutes=i),
            crear_perfil=(i == 0),
        )

    with TestClient(app) as client:
        cuerpo = client.get(SESIONES, headers=_auth(token), params={"limit": 2}).json()

    assert [item["title"] for item in cuerpo["items"]] == ["C0", "C1"]
    assert cuerpo["limit"] == 2


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_un_limite_fuera_de_rango_es_422(bd: BaseDeTest, limit: int) -> None:
    _, token = _usuario()
    with TestClient(app) as client:
        respuesta = client.get(SESIONES, headers=_auth(token), params={"limit": limit})
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "validation_error"


def test_sin_conversaciones_la_lista_va_vacia(bd: BaseDeTest) -> None:
    _, token = _usuario()
    with TestClient(app) as client:
        respuesta = client.get(SESIONES, headers=_auth(token))
    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == []


def test_listar_sin_token_es_401(bd: BaseDeTest) -> None:
    with TestClient(app) as client:
        assert client.get(SESIONES).status_code == 401


# --- GET /v1/chat/sessions/{id} ----------------------------------------------


def test_devuelve_el_historial_en_orden(bd: BaseDeTest) -> None:
    user_id, token = _usuario()
    conversation_id = _crear(
        bd,
        user_id=user_id,
        titulo="Cartagena",
        mensajes=[
            (MessageRole.USER, "¿Qué hago en Cartagena?"),
            (MessageRole.ASSISTANT, "Camina la ciudad amurallada."),
            (MessageRole.USER, "¿Y en diciembre?"),
        ],
    )

    with TestClient(app) as client:
        respuesta = client.get(f"{SESIONES}/{conversation_id}", headers=_auth(token))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["id"] == str(conversation_id)
    assert cuerpo["title"] == "Cartagena"
    assert [(m["role"], m["content"], m["sequence"]) for m in cuerpo["messages"]] == [
        ("user", "¿Qué hago en Cartagena?", 0),
        ("assistant", "Camina la ciudad amurallada.", 1),
        ("user", "¿Y en diciembre?", 2),
    ]


def test_el_historial_NUNCA_expone_los_tool_steps(bd: BaseDeTest) -> None:
    """La conversación SÍ los tiene guardados; la respuesta no debe traerlos.

    La frontera está en el TIPO (``SessionMessage`` no declara el campo), no en
    un filtro que alguien tenga que acordarse de aplicar.
    """
    user_id, token = _usuario()
    conversation_id = _crear(
        bd,
        user_id=user_id,
        titulo="Con herramientas",
        mensajes=[(MessageRole.ASSISTANT, "En Bogotá llueve.")],
        tool_steps=[{"tool": "clima", "raw": SEÑUELO}],
    )

    with TestClient(app) as client:
        respuesta = client.get(f"{SESIONES}/{conversation_id}", headers=_auth(token))

    # Están guardados de verdad…
    async def leer_pasos() -> list[dict[str, object]]:
        async with bd.factory() as session:
            filas = await session.execute(
                select(Message).where(Message.conversation_id == conversation_id)
            )
            return list(filas.scalars().all()[0].tool_steps)

    assert bd.run(leer_pasos) == [{"tool": "clima", "raw": SEÑUELO}]
    # …y no salieron por ningún lado.
    assert SEÑUELO not in respuesta.text
    assert "tool_steps" not in respuesta.text
    assert set(respuesta.json()["messages"][0]) == {"role", "content", "sequence", "created_at"}


def test_una_conversacion_ajena_inexistente_o_borrada_responden_LO_MISMO(
    bd: BaseDeTest,
) -> None:
    """Un 403 para la ajena convertiría el id en un oráculo de existencia."""
    user_id, token = _usuario()
    ajena = _crear(bd, user_id=uuid.uuid4(), titulo="De otra persona")
    borrada = _crear(bd, user_id=user_id, titulo="Borrada", borrada=True)

    with TestClient(app) as client:
        respuestas = [
            client.get(f"{SESIONES}/{ajena}", headers=_auth(token)),
            client.get(f"{SESIONES}/{borrada}", headers=_auth(token)),
            client.get(f"{SESIONES}/{uuid.uuid4()}", headers=_auth(token)),
        ]

    assert [r.status_code for r in respuestas] == [404, 404, 404]
    assert respuestas[0].json() == respuestas[1].json() == respuestas[2].json()
    assert respuestas[0].json()["error"]["code"] == "not_found"


def test_un_id_mal_formado_es_422(bd: BaseDeTest) -> None:
    _, token = _usuario()
    with TestClient(app) as client:
        respuesta = client.get(f"{SESIONES}/no-es-uuid", headers=_auth(token))
    assert respuesta.status_code == 422


def test_leer_sin_token_es_401(bd: BaseDeTest) -> None:
    with TestClient(app) as client:
        assert client.get(f"{SESIONES}/{uuid.uuid4()}").status_code == 401


# --- DELETE /v1/chat/sessions/{id} -------------------------------------------


def test_el_borrado_es_SOFT_y_saca_la_conversacion_de_todo(bd: BaseDeTest) -> None:
    user_id, token = _usuario()
    conversation_id = _crear(
        bd, user_id=user_id, titulo="Adiós", mensajes=[(MessageRole.USER, "hola")]
    )

    with TestClient(app) as client:
        borrado = client.delete(f"{SESIONES}/{conversation_id}", headers=_auth(token))
        listado = client.get(SESIONES, headers=_auth(token))
        lectura = client.get(f"{SESIONES}/{conversation_id}", headers=_auth(token))

    assert borrado.status_code == 204
    assert borrado.content == b""
    assert listado.json()["items"] == []
    assert lectura.status_code == 404

    # Soft: la fila sigue ahí, con fecha, y sus mensajes también. Es lo que
    # permite el purgado por retención y una recuperación por soporte (HU-2.3).
    fila = _leer_conversacion(bd, conversation_id)
    assert fila.deleted_at is not None
    assert fila.is_deleted


def test_tras_borrar_un_POST_chat_con_ese_id_responde_404(bd: BaseDeTest) -> None:
    doble = ProveedorDeChat(["hola"])
    set_llm_provider(doble)
    user_id, token = _usuario()
    conversation_id = _crear(bd, user_id=user_id, titulo="Adiós")

    with TestClient(app) as client:
        client.delete(f"{SESIONES}/{conversation_id}", headers=_auth(token))
        respuesta = client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "¿sigues ahí?", "conversation_id": str(conversation_id)},
        )

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "not_found"
    assert doble.llamadas == 0


def test_borrar_dos_veces_responde_404_la_segunda(bd: BaseDeTest) -> None:
    """La idempotencia cedería ante el 404 uniforme: un 204 diría "ese id era tuyo"."""
    user_id, token = _usuario()
    conversation_id = _crear(bd, user_id=user_id, titulo="Adiós")

    with TestClient(app) as client:
        primero = client.delete(f"{SESIONES}/{conversation_id}", headers=_auth(token))
        segundo = client.delete(f"{SESIONES}/{conversation_id}", headers=_auth(token))
        inventada = client.delete(f"{SESIONES}/{uuid.uuid4()}", headers=_auth(token))

    assert primero.status_code == 204
    assert segundo.status_code == 404
    assert segundo.json() == inventada.json()


def test_no_se_puede_borrar_la_conversacion_de_otra_persona(bd: BaseDeTest) -> None:
    otro = uuid.uuid4()
    ajena = _crear(bd, user_id=otro, titulo="De otra persona")
    _, token = _usuario()

    with TestClient(app) as client:
        respuesta = client.delete(f"{SESIONES}/{ajena}", headers=_auth(token))

    assert respuesta.status_code == 404
    # Y sigue viva para su dueño.
    assert _leer_conversacion(bd, ajena).deleted_at is None


def test_borrar_sin_token_es_401(bd: BaseDeTest) -> None:
    with TestClient(app) as client:
        assert client.delete(f"{SESIONES}/{uuid.uuid4()}").status_code == 401


# --- updated_at: la deuda que traía la HU-2.3 --------------------------------


def test_escribir_un_mensaje_TOCA_la_conversacion(bd: BaseDeTest) -> None:
    """Sin esto, la lista por actividad reciente ordenaría por fecha de creación.

    El síntoma habría sido una lista mal ordenada, no un error — por eso vale
    la pena un test explícito.
    """
    set_llm_provider(ProveedorDeChat(["ok"]))
    user_id, token = _usuario()
    viejo = datetime(2020, 1, 1, tzinfo=UTC)
    conversation_id = _crear(bd, user_id=user_id, titulo="Retomada", actividad=viejo)

    antes = _leer_conversacion(bd, conversation_id).updated_at

    with TestClient(app) as client:
        client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "volví", "conversation_id": str(conversation_id)},
        )

    despues = _leer_conversacion(bd, conversation_id).updated_at
    assert despues > antes
    assert despues.year > 2020


def test_retomar_una_conversacion_vieja_la_sube_al_principio_de_la_lista(
    bd: BaseDeTest,
) -> None:
    """El recorrido completo de la deuda: escribir, y que la lista lo refleje."""
    set_llm_provider(ProveedorDeChat(["ok"]))
    user_id, token = _usuario()
    ahora = datetime.now(UTC)
    vieja = _crear(bd, user_id=user_id, titulo="Vieja", actividad=ahora - timedelta(days=30))
    _crear(
        bd,
        user_id=user_id,
        titulo="Reciente",
        actividad=ahora - timedelta(minutes=1),
        crear_perfil=False,
    )

    with TestClient(app) as client:
        antes = client.get(SESIONES, headers=_auth(token)).json()
        client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "volví", "conversation_id": str(vieja)},
        )
        despues = client.get(SESIONES, headers=_auth(token)).json()

    assert [i["title"] for i in antes["items"]] == ["Reciente", "Vieja"]
    assert [i["title"] for i in despues["items"]] == ["Vieja", "Reciente"]


def test_una_conversacion_nueva_aparece_en_la_lista(bd: BaseDeTest) -> None:
    set_llm_provider(ProveedorDeChat(["ok"]))
    _, token = _usuario()

    with TestClient(app) as client:
        chat = client.post("/v1/chat", headers=_auth(token), json={"message": "¿qué hago en Cali?"})
        conversation_id = eventos_de(chat.text)[0]["conversation_id"]
        cuerpo = client.get(SESIONES, headers=_auth(token)).json()

    assert [i["id"] for i in cuerpo["items"]] == [conversation_id]
    assert cuerpo["items"][0]["title"] == "¿qué hago en Cali?"


# --- Rate limiting -----------------------------------------------------------


def test_la_cuota_por_usuario_aplica_a_las_sesiones(
    bd: BaseDeTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_default_limit", 1_000)
    monkeypatch.setattr(settings, "rate_limit_user_limit", 2)
    monkeypatch.setattr(settings, "rate_limit_user_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_pro_multiplier", 1.0)
    _, token = _usuario()

    with TestClient(app) as client:
        codigos = [client.get(SESIONES, headers=_auth(token)).status_code for _ in range(3)]

    assert codigos == [200, 200, 429]
