"""Tests de la memoria del chat: ventana por tokens y contexto multi-turno (HU-2.5).

Dos capas, a propósito separadas:

1. **El recorte a solas** (``estimate_tokens`` / ``trim_to_budget``): son
   funciones puras sobre una lista de mensajes, y probarlas sin base de datos
   ni endpoint deja que el caso raro —el corte que parte un par
   pregunta/respuesta— se escriba en tres líneas.
2. **El turno completo**, contra el endpoint, verificando lo que de verdad
   importa: **qué recibió el modelo**. El doble del proveedor guarda los
   mensajes que le llegaron, así que se puede afirmar sobre el contexto en vez
   de deducirlo de la respuesta.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import Conversation, Message, MessageRole, UserProfile
from app.services import chat
from app.services.llm import LLMUnavailable, set_llm_provider
from tests import auth_utils
from tests.conftest import BaseDeTest
from tests.test_chat import ProveedorDeChat, eventos_de


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_utils.install_auth_env(monkeypatch)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _msg(role: MessageRole, content: str, sequence: int = 0) -> Message:
    """Mensaje suelto, sin base de datos: para probar el recorte a solas."""
    return Message(conversation_id=uuid.uuid4(), role=role, sequence=sequence, content=content)


def _hilo(*textos: str) -> list[Message]:
    """Historial que alterna user/assistant empezando por user."""
    roles = (MessageRole.USER, MessageRole.ASSISTANT)
    return [_msg(roles[i % 2], texto, i) for i, texto in enumerate(textos)]


# --- El estimador de tokens --------------------------------------------------


def test_el_estimador_es_pesimista_a_proposito() -> None:
    """Cuenta a 3 caracteres por token cuando el español real ronda 3,5-4.

    Sobreestimar recorta memoria vieja de más; subestimar manda más contexto
    del que cabe y el proveedor responde 400. Los dos errores no cuestan lo
    mismo, y el estimador se inclina al barato.
    """
    texto = "x" * 300  # ~75-85 tokens reales en español
    estimado = chat.estimate_tokens(texto)

    assert estimado == 4 + 100  # envoltorio del mensaje + 300/3
    assert estimado > 85


def test_el_estimador_cobra_el_envoltorio_de_cada_mensaje() -> None:
    """Un mensaje vacío no cuesta cero: el rol y los delimitadores se pagan."""
    assert chat.estimate_tokens("") == 4
    # Diez mensajes de una palabra cuestan más que uno de diez palabras.
    diez_cortos = sum(chat.estimate_tokens("hola") for _ in range(10))
    uno_largo = chat.estimate_tokens("hola " * 10)
    assert diez_cortos > uno_largo


def test_la_relacion_caracteres_por_token_es_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se ajusta contra el llm_input_tokens real de la HU-2.1, sin tocar código."""
    monkeypatch.setattr(settings, "chat_context_chars_per_token", 4.0)
    assert chat.estimate_tokens("x" * 400) == 4 + 100


# --- El recorte por presupuesto ----------------------------------------------


def test_sin_presion_de_presupuesto_se_conserva_todo_el_historial() -> None:
    historial = _hilo("hola", "¿a dónde vamos?", "a Cali", "buena elección")
    assert chat.trim_to_budget(historial, budget=10_000) == historial


def test_se_conservan_los_mensajes_RECIENTES_y_se_tiran_los_viejos() -> None:
    """Lo que da sentido a la pregunta de ahora es lo último, no lo primero."""
    historial = _hilo(*[f"mensaje {i} " + "x" * 90 for i in range(6)])

    # Cada mensaje cuesta 4 + ~33 = ~37 tokens; con 80 caben dos.
    recortado = chat.trim_to_budget(historial, budget=80)

    assert [m.sequence for m in recortado] == [4, 5]


def test_un_presupuesto_de_cero_deja_el_historial_vacio() -> None:
    """El turno se comporta como el primero: honesto, no un error."""
    assert chat.trim_to_budget(_hilo("hola", "qué tal"), budget=0) == []


def test_el_recorte_NO_se_salta_un_mensaje_del_medio_para_encajar_uno_viejo() -> None:
    """Un hueco en el medio haría que el modelo emparejara mal pregunta y respuesta."""
    historial = _hilo(
        "corto",  # 0 — cabría de sobra
        "x" * 3000,  # 1 — enorme: aquí se para el recorrido hacia atrás
        "reciente uno",  # 2
        "reciente dos",  # 3
    )

    recortado = chat.trim_to_budget(historial, budget=60)

    # Se para en el gigante y no rescata el "corto" que había antes.
    assert [m.sequence for m in recortado] == [2, 3]


# --- El borde: la respuesta huérfana ----------------------------------------


def test_el_historial_nunca_empieza_por_una_respuesta_huerfana() -> None:
    """Si el corte parte un par, el ``assistant`` sin su pregunta se descarta.

    El modelo lo leería como algo que Rover dijo por su cuenta —y suele ser
    media respuesta a algo invisible, que invita a continuarla en vez de
    atender lo que se pregunta ahora.
    """
    historial = _hilo(*[f"turno {i} " + "x" * 90 for i in range(6)])

    # Un presupuesto que deja entrar 3 mensajes: 5 (assistant), 4 (user) y
    # 3 (assistant), o sea empezando por un assistant huérfano.
    recortado = chat.trim_to_budget(historial, budget=115)

    assert [m.sequence for m in recortado] == [4, 5]
    assert recortado[0].role is MessageRole.USER


def test_si_al_quitar_el_huerfano_no_queda_nada_el_historial_va_vacio() -> None:
    historial = [_msg(MessageRole.ASSISTANT, "una respuesta suelta", 0)]
    assert chat.trim_to_budget(historial, budget=10_000) == []


def test_el_recorte_conserva_el_orden_original() -> None:
    historial = _hilo("uno", "dos", "tres", "cuatro")
    recortado = chat.trim_to_budget(historial, budget=10_000)
    assert [m.sequence for m in recortado] == [0, 1, 2, 3]


# --- Los tool_steps NO viajan al contexto ------------------------------------


def test_los_tool_steps_no_entran_en_el_contexto_del_modelo() -> None:
    """Están caducados, cuestan mucho y su conclusión ya está en ``content``."""
    mensaje = _msg(MessageRole.ASSISTANT, "En Bogotá llueve.", 1)
    mensaje.tool_steps = [{"tool": "clima", "args": {"ciudad": "Bogotá"}, "result": {"mm": 12}}]

    contexto = chat.build_context(mensaje="¿y mañana?", historial=[mensaje])

    textos = [m.content for m in contexto]
    assert textos == ["En Bogotá llueve.", "¿y mañana?"]
    assert not any("clima" in t or "mm" in t for t in textos)


def test_un_turno_del_asistente_sin_texto_no_ensucia_el_contexto() -> None:
    """Posible desde la HU-2.6: un turno que fue solo herramientas."""
    historial = [_msg(MessageRole.USER, "¿llueve?", 0), _msg(MessageRole.ASSISTANT, "", 1)]
    contexto = chat.build_context(mensaje="¿y mañana?", historial=historial)
    assert [m.content for m in contexto] == ["¿llueve?", "¿y mañana?"]


def test_el_mensaje_nuevo_va_SIEMPRE_al_final() -> None:
    """Stable-prefix-first: lo estable delante, lo de ahora al final."""
    contexto = chat.build_context(mensaje="lo de ahora", historial=_hilo("a", "b"))
    assert contexto[-1].content == "lo de ahora"
    assert contexto[-1].role.value == "user"


# --- El turno completo, contra el endpoint -----------------------------------


def _conversacion_con_turnos(
    bd: BaseDeTest, *, user_id: uuid.UUID, textos: list[tuple[MessageRole, str]]
) -> uuid.UUID:
    conversation_id = uuid.uuid4()

    async def escribir() -> None:
        async with bd.factory() as session:
            session.add(UserProfile(id=user_id, email="viajera@example.com"))
            await session.flush()
            session.add(Conversation(id=conversation_id, user_id=user_id, title="Hilo"))
            await session.flush()
            for i, (role, content) in enumerate(textos):
                session.add(
                    Message(conversation_id=conversation_id, role=role, sequence=i, content=content)
                )
            await session.commit()

    bd.run(escribir)
    return conversation_id


def test_multiturno_el_modelo_recibe_la_conversacion_previa_en_orden(
    bd: BaseDeTest,
) -> None:
    """La pregunta de seguimiento solo tiene sentido con lo anterior delante."""

    doble = ProveedorDeChat(["En diciembre ", "también."])
    set_llm_provider(doble)

    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))
    conversation_id = _conversacion_con_turnos(
        bd,
        user_id=user_id,
        textos=[
            (MessageRole.USER, "¿Qué hago en Cartagena?"),
            (MessageRole.ASSISTANT, "Camina la ciudad amurallada al atardecer."),
        ],
    )

    with TestClient(app) as client:
        respuesta = client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "¿Y en diciembre?", "conversation_id": str(conversation_id)},
        )

    assert respuesta.status_code == 200
    # ESTO es lo que hace que Rover "recuerde": lo que se le mandó al modelo.
    assert [(m.role.value, m.content) for m in doble.recibido] == [
        ("user", "¿Qué hago en Cartagena?"),
        ("assistant", "Camina la ciudad amurallada al atardecer."),
        ("user", "¿Y en diciembre?"),
    ]
    # Y el prefijo estable sigue yendo aparte, no como un mensaje más.
    assert doble.system_prompt is not None
    assert "Rover" in doble.system_prompt


def test_una_conversacion_nueva_no_arrastra_historial_de_ninguna_parte(
    bd: BaseDeTest,
) -> None:

    doble = ProveedorDeChat(["hola"])
    set_llm_provider(doble)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))
    # Otra conversación del MISMO usuario, con contenido.
    _conversacion_con_turnos(
        bd, user_id=user_id, textos=[(MessageRole.USER, "secreto de otra conversación")]
    )

    with TestClient(app) as client:
        client.post("/v1/chat", headers=_auth(token), json={"message": "empezamos"})

    assert [m.content for m in doble.recibido] == ["empezamos"]


def test_el_presupuesto_recorta_el_contexto_del_endpoint(
    bd: BaseDeTest, monkeypatch: pytest.MonkeyPatch
) -> None:

    doble = ProveedorDeChat(["ok"])
    set_llm_provider(doble)
    monkeypatch.setattr(settings, "chat_context_token_budget", 60)

    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))
    conversation_id = _conversacion_con_turnos(
        bd,
        user_id=user_id,
        textos=[
            (MessageRole.USER, "viejo " + "x" * 200),
            (MessageRole.ASSISTANT, "respuesta vieja " + "x" * 200),
            (MessageRole.USER, "reciente"),
            (MessageRole.ASSISTANT, "respuesta reciente"),
        ],
    )

    with TestClient(app) as client:
        client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "y ahora?", "conversation_id": str(conversation_id)},
        )

    assert [m.content for m in doble.recibido] == [
        "reciente",
        "respuesta reciente",
        "y ahora?",
    ]


def test_el_turno_que_se_acaba_de_guardar_no_se_duplica_en_el_contexto(
    bd: BaseDeTest,
) -> None:
    """El historial se lee ANTES de escribir la pregunta: no llega dos veces."""

    doble = ProveedorDeChat(["ok"])
    set_llm_provider(doble)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))
    conversation_id = _conversacion_con_turnos(
        bd, user_id=user_id, textos=[(MessageRole.USER, "primera")]
    )

    with TestClient(app) as client:
        client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "segunda", "conversation_id": str(conversation_id)},
        )

    assert [m.content for m in doble.recibido].count("segunda") == 1


def test_dos_turnos_seguidos_acumulan_memoria(bd: BaseDeTest) -> None:
    """El recorrido real: preguntar, y que la siguiente pregunta ya tenga contexto."""

    doble = ProveedorDeChat(["Cali."])
    set_llm_provider(doble)
    token = auth_utils.make_token(sub=str(uuid.uuid4()))

    with TestClient(app) as client:
        primera = client.post("/v1/chat", headers=_auth(token), json={"message": "¿a dónde voy?"})
        conversation_id = eventos_de(primera.text)[0]["conversation_id"]
        client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "¿y qué como allá?", "conversation_id": conversation_id},
        )

    assert [(m.role.value, m.content) for m in doble.recibido] == [
        ("user", "¿a dónde voy?"),
        ("assistant", "Cali."),
        ("user", "¿y qué como allá?"),
    ]


def test_una_respuesta_abandonada_no_reaparece_en_el_contexto(bd: BaseDeTest) -> None:
    """La otra mitad de la decisión de la HU-2.4, vista desde la memoria.

    Como la parcial no se persistió, el turno siguiente no la reenvía: el
    modelo no lee su propio texto truncado como si lo hubiera dicho.
    """
    roto = ProveedorDeChat(["Te cuento: ", "el mejor"], fallo_en=1, error=LLMUnavailable("caído"))
    set_llm_provider(roto)
    token = auth_utils.make_token(sub=str(uuid.uuid4()))

    with TestClient(app) as client:
        primera = client.post("/v1/chat", headers=_auth(token), json={"message": "¿dónde como?"})
        conversation_id = eventos_de(primera.text)[0]["conversation_id"]

        sano = ProveedorDeChat(["Ahora sí."])
        set_llm_provider(sano)
        client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "¿hola?", "conversation_id": conversation_id},
        )

    assert [(m.role.value, m.content) for m in sano.recibido] == [
        ("user", "¿dónde como?"),
        ("user", "¿hola?"),
    ]
    assert not any("Te cuento" in m.content for m in sano.recibido)


def test_el_contexto_de_otra_conversacion_nunca_se_mezcla(bd: BaseDeTest) -> None:

    doble = ProveedorDeChat(["ok"])
    set_llm_provider(doble)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))
    _conversacion_con_turnos(bd, user_id=user_id, textos=[(MessageRole.USER, "hilo A")])
    hilo_b = uuid.uuid4()

    async def crear_b() -> None:
        async with bd.factory() as session:
            session.add(Conversation(id=hilo_b, user_id=user_id, title="B"))
            await session.flush()
            session.add(
                Message(conversation_id=hilo_b, role=MessageRole.USER, sequence=0, content="hilo B")
            )
            await session.commit()

    bd.run(crear_b)

    with TestClient(app) as client:
        client.post(
            "/v1/chat",
            headers=_auth(token),
            json={"message": "sigue", "conversation_id": str(hilo_b)},
        )

    assert [m.content for m in doble.recibido] == ["hilo B", "sigue"]
