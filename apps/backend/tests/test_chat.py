"""Tests de ``POST /v1/chat`` — SIN DeepSeek real y sin base de datos real.

El proveedor de LLM se sustituye por un doble que implementa el ``Protocol``
de la HU-2.1 (``set_llm_provider``, aislado por ``conftest``), y la base la
entrega la fixture ``bd`` de la HU-1.13. Los tokens se firman aquí mismo
(``tests/auth_utils.py``).

El foco de este módulo NO es "¿responde 200?": es lo que queda escrito en la
base después de cada uno de los tres finales posibles de un stream —completo,
roto a mitad, abandonado por el cliente—, que es la parte de esta HU que no
falla ruidosamente si se rompe.
"""

import json
import uuid
from collections.abc import AsyncGenerator, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from anyio.abc import BlockingPortal
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.api.v1 import chat as chat_endpoint
from app.core.config import settings
from app.main import app
from app.models import Conversation, Message, MessageRole, UserProfile
from app.services import chat as chat_service
from app.services.llm import (
    Capability,
    Completion,
    CompletionChunk,
    LLMBadRequest,
    LLMError,
    LLMNotConfigured,
    LLMProvider,
    LLMRateLimited,
    LLMUnavailable,
    set_llm_provider,
)
from app.services.llm import Message as LLMMessage
from app.services.llm import Role as LLMRole
from tests import auth_utils
from tests.conftest import BaseDeTest


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_utils.install_auth_env(monkeypatch)


# --- Doble del proveedor -----------------------------------------------------


class ProveedorDeChat:
    """Proveedor de mentira con los tres finales del stream y contador de cierres.

    ``fallo_en`` inyecta un error del proveedor: en ``0`` falla ANTES del primer
    trozo (el caso que todavía puede salir como status HTTP), y en ``n > 0``
    falla ya empezado el stream. ``cerrado`` registra si alguien llamó a
    ``aclose()`` — es lo único que distingue un cliente que se va limpiamente
    de una conexión con DeepSeek que queda colgando.
    """

    def __init__(
        self,
        trozos: Sequence[str] = ("Hola, ", "soy Rover."),
        *,
        fallo_en: int | None = None,
        error: LLMError | None = None,
    ) -> None:
        self._trozos = list(trozos)
        self._fallo_en = fallo_en
        self._error = error or LLMUnavailable("Rover no está disponible.")
        self.cerrado = False
        self.recibido: list[LLMMessage] = []
        self.system_prompt: str | None = None
        self.llamadas = 0

    @property
    def model(self) -> str:
        return "modelo-de-mentira"

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.TEXT})

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> Completion:  # pragma: no cover - el chat solo usa streaming
        return Completion(text="".join(self._trozos), model=self.model)

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncGenerator[CompletionChunk]:
        self.recibido = list(messages)
        self.system_prompt = system_prompt
        self.llamadas += 1
        try:
            for indice, trozo in enumerate(self._trozos):
                if self._fallo_en == indice:
                    raise self._error
                yield CompletionChunk(text=trozo)
            if self._fallo_en == len(self._trozos):
                raise self._error
            # Trozo final sin texto, como el real: solo trae el consumo.
            yield CompletionChunk(text="", finish_reason="stop")
        finally:
            self.cerrado = True


@pytest.fixture
def proveedor() -> Iterator[ProveedorDeChat]:
    doble = ProveedorDeChat()
    set_llm_provider(doble)
    yield doble


def _instalar(doble: ProveedorDeChat) -> ProveedorDeChat:
    """Registra un doble distinto del de la fixture (casos de error)."""
    set_llm_provider(doble)
    return doble


# --- Utilidades --------------------------------------------------------------


#: Origen que la config de desarrollo permite de fábrica (``_DEV_CORS_ORIGINS``).
_ORIGEN_WEB = "http://localhost:3000"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token(user_id: uuid.UUID | None = None) -> tuple[uuid.UUID, str]:
    uid = user_id or uuid.uuid4()
    return uid, auth_utils.make_token(sub=str(uid))


def eventos_de(cuerpo: str) -> list[dict[str, Any]]:
    """Parsea el cuerpo SSE a la lista de payloads JSON, en orden."""
    marcos = [m for m in cuerpo.split("\n\n") if m.strip()]
    payloads: list[dict[str, Any]] = []
    for marco in marcos:
        assert marco.startswith("data: "), f"marco sin data:: {marco!r}"
        payloads.append(json.loads(marco[len("data: ") :]))
    return payloads


def _de_tipo(eventos: list[dict[str, Any]], tipo: str) -> list[dict[str, Any]]:
    return [e for e in eventos if e["type"] == tipo]


def _texto(eventos: list[dict[str, Any]]) -> str:
    return "".join(e["text"] for e in _de_tipo(eventos, "delta"))


def _mensajes(bd: BaseDeTest, conversation_id: uuid.UUID) -> list[Message]:
    async def leer() -> list[Message]:
        async with bd.factory() as session:
            filas = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sequence)
            )
            return list(filas.scalars().all())

    return bd.run(leer)


def _conversaciones(bd: BaseDeTest) -> list[Conversation]:
    async def leer() -> list[Conversation]:
        async with bd.factory() as session:
            filas = await session.execute(select(Conversation))
            return list(filas.scalars().all())

    return bd.run(leer)


def _crear_conversacion(bd: BaseDeTest, *, user_id: uuid.UUID, titulo: str = "Vieja") -> uuid.UUID:
    """Conversación previa CON su perfil, como la dejaría un turno anterior."""
    conversation_id = uuid.uuid4()

    async def escribir() -> None:
        async with bd.factory() as session:
            session.add(UserProfile(id=user_id, email="previa@example.com"))
            await session.flush()
            session.add(Conversation(id=conversation_id, user_id=user_id, title=titulo))
            await session.flush()
            session.add(
                Message(
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    sequence=0,
                    content="Hola",
                )
            )
            session.add(
                Message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    sequence=1,
                    content="Hola, ¿a dónde vamos?",
                )
            )
            await session.commit()

    bd.run(escribir)
    return conversation_id


def _post(client: TestClient, token: str, **cuerpo: Any) -> Any:
    return client.post("/v1/chat", headers=_auth(token), json=cuerpo)


# --- Caso feliz --------------------------------------------------------------


def test_crea_la_conversacion_y_persiste_los_dos_mensajes(
    bd: BaseDeTest, proveedor: ProveedorDeChat
) -> None:
    user_id, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="¿Qué hago en Cartagena?")

    assert respuesta.status_code == 200
    eventos = eventos_de(respuesta.text)

    # El primer evento identifica la conversación: es lo que el cliente
    # necesita para saber a cuál pertenece lo que está a punto de leer.
    assert eventos[0]["type"] == "start"
    assert eventos[0]["created"] is True
    conversation_id = uuid.UUID(eventos[0]["conversation_id"])

    conversaciones = _conversaciones(bd)
    assert [c.id for c in conversaciones] == [conversation_id]
    assert conversaciones[0].user_id == user_id
    assert conversaciones[0].deleted_at is None

    mensajes = _mensajes(bd, conversation_id)
    assert [(m.role, m.sequence, m.content) for m in mensajes] == [
        (MessageRole.USER, 0, "¿Qué hago en Cartagena?"),
        (MessageRole.ASSISTANT, 1, "Hola, soy Rover."),
    ]
    # Los pasos de tool-calling nacen vacíos: las tools son la HU-2.6.
    assert all(m.tool_steps == [] for m in mensajes)


def test_los_trozos_llegan_en_orden_y_reconstruyen_la_respuesta(
    bd: BaseDeTest,
) -> None:
    _instalar(ProveedorDeChat(["Bo", "go", "tá"]))
    _, token = _token()

    with TestClient(app) as client:
        with client.stream("POST", "/v1/chat", headers=_auth(token), json={"message": "?"}) as r:
            assert r.status_code == 200
            cuerpo = "".join(r.iter_text())

    eventos = eventos_de(cuerpo)
    assert [e["type"] for e in eventos] == ["start", "delta", "delta", "delta", "done"]
    assert [e["text"] for e in _de_tipo(eventos, "delta")] == ["Bo", "go", "tá"]
    # El contrato del stream: concatenar los deltas da la respuesta guardada.
    conversation_id = uuid.UUID(eventos[0]["conversation_id"])
    assert _texto(eventos) == _mensajes(bd, conversation_id)[1].content


def test_el_evento_final_trae_el_sequence_del_mensaje_del_asistente(
    bd: BaseDeTest, proveedor: ProveedorDeChat
) -> None:
    _, token = _token()
    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola")

    eventos = eventos_de(respuesta.text)
    assert _de_tipo(eventos, "done") == [{"type": "done", "sequence": 1}]


def test_las_cabeceras_evitan_el_buffering_de_los_proxies(
    bd: BaseDeTest, proveedor: ProveedorDeChat
) -> None:
    """Sin estas cabeceras el stream funciona… y llega entero al final."""
    _, token = _token()
    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola")

    assert respuesta.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert respuesta.headers["cache-control"] == "no-cache, no-transform"
    assert respuesta.headers["x-accel-buffering"] == "no"


def test_el_titulo_se_deriva_del_primer_mensaje(bd: BaseDeTest, proveedor: ProveedorDeChat) -> None:
    _, token = _token()
    with TestClient(app) as client:
        _post(client, token, message="  ¿Qué\n  hago   en Cali?  ")

    assert _conversaciones(bd)[0].title == "¿Qué hago en Cali?"


def test_el_titulo_largo_se_corta(bd: BaseDeTest, proveedor: ProveedorDeChat) -> None:
    _, token = _token()
    largo = "Quiero un itinerario detallado de dos semanas por toda Colombia con presupuesto"

    with TestClient(app) as client:
        _post(client, token, message=largo)

    titulo = _conversaciones(bd)[0].title
    assert len(titulo) <= chat_service.MAX_TITULO_CHARS
    assert titulo.endswith("…")
    assert largo.startswith(titulo[:-1])


def test_el_contexto_lleva_el_mensaje_y_la_personalidad_de_rover(
    bd: BaseDeTest, proveedor: ProveedorDeChat
) -> None:
    """El system prompt (HU-2.2) va APARTE, como prefijo estable, no en la lista."""
    _, token = _token()
    with TestClient(app) as client:
        _post(client, token, message="¿llueve?")

    assert [(m.role.value, m.content) for m in proveedor.recibido] == [("user", "¿llueve?")]
    assert proveedor.system_prompt is not None
    assert "Rover" in proveedor.system_prompt


# --- Continuar una conversación ----------------------------------------------


def test_continuar_una_conversacion_usa_el_siguiente_sequence(
    bd: BaseDeTest, proveedor: ProveedorDeChat
) -> None:
    user_id, token = _token()
    conversation_id = _crear_conversacion(bd, user_id=user_id)

    with TestClient(app) as client:
        respuesta = _post(
            client, token, message="¿Y en diciembre?", conversation_id=str(conversation_id)
        )

    assert respuesta.status_code == 200
    eventos = eventos_de(respuesta.text)
    assert eventos[0]["conversation_id"] == str(conversation_id)
    # No es nueva: el cliente no debe añadirla otra vez a su lista.
    assert eventos[0]["created"] is False

    mensajes = _mensajes(bd, conversation_id)
    assert [(m.role, m.sequence) for m in mensajes] == [
        (MessageRole.USER, 0),
        (MessageRole.ASSISTANT, 1),
        (MessageRole.USER, 2),
        (MessageRole.ASSISTANT, 3),
    ]
    assert mensajes[2].content == "¿Y en diciembre?"
    # Continuar NO crea una conversación nueva.
    assert len(_conversaciones(bd)) == 1


def test_continuar_no_reescribe_el_titulo(bd: BaseDeTest, proveedor: ProveedorDeChat) -> None:
    user_id, token = _token()
    conversation_id = _crear_conversacion(bd, user_id=user_id, titulo="Cartagena en junio")

    with TestClient(app) as client:
        _post(client, token, message="otra cosa", conversation_id=str(conversation_id))

    assert _conversaciones(bd)[0].title == "Cartagena en junio"


# --- Pertenencia: nada revela la existencia de conversaciones ajenas ----------


def test_la_conversacion_de_otro_usuario_responde_404(
    bd: BaseDeTest, proveedor: ProveedorDeChat
) -> None:
    ajena = _crear_conversacion(bd, user_id=uuid.uuid4())
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola", conversation_id=str(ajena))

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "not_found"
    # No se le añadió NADA a la conversación ajena.
    assert len(_mensajes(bd, ajena)) == 2
    # Y no se llamó al modelo: no se pagan tokens por un intento de acceso.
    assert proveedor.llamadas == 0


def test_una_conversacion_inexistente_responde_EXACTAMENTE_lo_mismo(
    bd: BaseDeTest, proveedor: ProveedorDeChat
) -> None:
    """404 idéntico: si el ajeno diera 403, el id sería un oráculo de existencia."""
    ajena = _crear_conversacion(bd, user_id=uuid.uuid4())
    _, token = _token()

    with TestClient(app) as client:
        de_otro = _post(client, token, message="hola", conversation_id=str(ajena))
        inventada = _post(client, token, message="hola", conversation_id=str(uuid.uuid4()))

    assert de_otro.status_code == inventada.status_code == 404
    assert de_otro.json() == inventada.json()


def test_una_conversacion_borrada_responde_404(bd: BaseDeTest, proveedor: ProveedorDeChat) -> None:
    """El soft-delete (HU-2.3) saca la conversación del alcance del chat."""
    user_id, token = _token()
    conversation_id = _crear_conversacion(bd, user_id=user_id)

    async def borrar() -> None:
        async with bd.factory() as session:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(deleted_at=datetime.now(UTC))
            )
            await session.commit()

    bd.run(borrar)

    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola", conversation_id=str(conversation_id))

    assert respuesta.status_code == 404
    assert len(_mensajes(bd, conversation_id)) == 2


# --- Auth y validación del cuerpo --------------------------------------------


def test_sin_token_responde_401(bd: BaseDeTest, proveedor: ProveedorDeChat) -> None:
    with TestClient(app) as client:
        respuesta = client.post("/v1/chat", json={"message": "hola"})

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "unauthenticated"
    assert _conversaciones(bd) == []


def test_token_invalido_responde_401(bd: BaseDeTest, proveedor: ProveedorDeChat) -> None:
    with TestClient(app) as client:
        respuesta = _post(client, "no-es-un-jwt", message="hola")
    assert respuesta.status_code == 401


@pytest.mark.parametrize(
    ("cuerpo", "motivo"),
    [
        ({"message": ""}, "vacío"),
        ({"message": "   \n  "}, "solo espacios"),
        ({"message": "x" * 8001}, "demasiado largo"),
        ({}, "sin mensaje"),
        ({"message": "hola", "user_id": "otro"}, "campo de más"),
        ({"message": "hola", "conversation_id": "no-es-uuid"}, "id mal formado"),
    ],
)
def test_cuerpos_invalidos_responden_422(
    bd: BaseDeTest, proveedor: ProveedorDeChat, cuerpo: dict[str, Any], motivo: str
) -> None:
    """``extra='forbid'`` importa aquí: el dueño sale del token, no del cuerpo."""
    _, token = _token()
    with TestClient(app) as client:
        respuesta = client.post("/v1/chat", headers=_auth(token), json=cuerpo)

    assert respuesta.status_code == 422, motivo
    assert respuesta.json()["error"]["code"] == "validation_error"
    assert proveedor.llamadas == 0


# --- Fallo (1): ANTES del stream → status HTTP normal -------------------------


@pytest.mark.parametrize(
    ("error", "status_esperado", "code_esperado"),
    [
        (LLMUnavailable("no disponible"), 503, "service_unavailable"),
        (LLMNotConfigured("sin key"), 503, "service_unavailable"),
        (LLMRateLimited("saturado"), 429, "rate_limited"),
        (LLMBadRequest("contexto largo"), 422, "validation_error"),
    ],
)
def test_error_antes_del_stream_responde_con_status_http(
    bd: BaseDeTest, error: LLMError, status_esperado: int, code_esperado: str
) -> None:
    """Nada salió aún por el cable: todavía se puede responder como siempre."""
    doble = _instalar(ProveedorDeChat(["hola"], fallo_en=0, error=error))
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola")

    assert respuesta.status_code == status_esperado
    assert respuesta.json()["error"]["code"] == code_esperado
    assert respuesta.headers["content-type"].startswith("application/json")
    assert doble.cerrado is True


def test_un_fallo_antes_del_stream_NO_deja_rastro_en_la_base(bd: BaseDeTest) -> None:
    """El turno se escribe DESPUÉS del primer trozo: reintentar es limpio."""
    _instalar(ProveedorDeChat(["hola"], fallo_en=0))
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola")

    assert respuesta.status_code == 503
    assert _conversaciones(bd) == []


def test_el_mensaje_del_error_no_filtra_el_diagnostico_del_proveedor(bd: BaseDeTest) -> None:
    _instalar(
        ProveedorDeChat(
            ["hola"],
            fallo_en=0,
            error=LLMUnavailable(
                "Rover no está disponible.",
                provider_status=402,
                provider_error_code="insufficient_balance",
                provider_message="Insufficient Balance",
            ),
        )
    )
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola")

    cuerpo = respuesta.text
    assert "Insufficient" not in cuerpo
    assert "insufficient_balance" not in cuerpo
    assert "402" not in cuerpo


# --- Fallo (2): A MITAD del stream → evento de error dentro del SSE -----------


def test_error_a_mitad_emite_un_evento_de_error_con_el_formato_de_la_hu_1_8(
    bd: BaseDeTest,
) -> None:
    doble = _instalar(ProveedorDeChat(["Voy a ", "contarte"], fallo_en=1))
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="hola")

    # El status ya se había mandado: es 200 y no puede ser otra cosa.
    assert respuesta.status_code == 200
    eventos = eventos_de(respuesta.text)
    assert [e["type"] for e in eventos] == ["start", "delta", "error"]

    error = eventos[-1]["error"]
    # Mismas claves y mismo catálogo de ``code`` que un error HTTP.
    assert set(error) == {"code", "message", "details", "error_id"}
    assert error["code"] == "service_unavailable"
    assert error["details"] is None
    # Y el stream se cerró limpio, sin dejar la conexión del proveedor viva.
    assert doble.cerrado is True


def test_error_a_mitad_NO_persiste_la_respuesta_parcial(bd: BaseDeTest) -> None:
    """Una fila ``assistant`` a medias envenenaría el contexto de la HU-2.5."""
    _instalar(ProveedorDeChat(["Te cuento: ", "el mejor"], fallo_en=1))
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="¿dónde como?")

    conversation_id = uuid.UUID(eventos_de(respuesta.text)[0]["conversation_id"])
    mensajes = _mensajes(bd, conversation_id)
    # Queda la pregunta (pasó de verdad) y NO queda respuesta.
    assert [(m.role, m.content) for m in mensajes] == [(MessageRole.USER, "¿dónde como?")]


def test_error_a_mitad_loguea_la_causa_real_con_el_request_id(
    bd: BaseDeTest, caplog: pytest.LogCaptureFixture
) -> None:
    _instalar(
        ProveedorDeChat(
            ["hola "],
            fallo_en=1,
            error=LLMUnavailable(
                "Rover no está disponible.",
                provider_status=502,
                provider_error_code="upstream_down",
                provider_message="Bad Gateway",
            ),
        )
    )
    _, token = _token()

    with caplog.at_level("WARNING", logger="app.api.v1.chat"):
        with TestClient(app) as client:
            respuesta = _post(client, token, message="hola")

    registros = [r for r in caplog.records if r.name == "app.api.v1.chat"]
    assert len(registros) == 1
    registro = registros[0]
    assert registro.chat_stage == "a mitad"  # type: ignore[attr-defined]
    assert registro.llm_provider_status == 502  # type: ignore[attr-defined]
    # El id de petición sigue disponible dentro del generador del stream.
    assert getattr(registro, "request_id", None) == respuesta.headers["x-request-id"]


# --- Fallo (3): el cliente se va ---------------------------------------------


def test_el_aborto_del_cliente_cierra_el_generador_y_no_persiste_nada(
    bd: BaseDeTest, loop_de_test: BlockingPortal
) -> None:
    """Se ejerce el generador directamente: un TCP cortado no se simula bien.

    Es el mismo camino que recorre Starlette al detectar la desconexión —
    cancelar la tarea que consume el generador acaba en su ``aclose()``.
    """
    doble = ProveedorDeChat(["uno", "dos", "tres"])
    conversation_id = uuid.uuid4()

    async def a_medias() -> list[dict[str, Any]]:
        stream = doble.stream([LLMMessage(role=LLMRole.USER, content="hola")])
        primero = await anext(stream)
        eventos = chat_endpoint._eventos(
            stream, primero=primero, conversation_id=conversation_id, creada=True
        )
        leidos = [await anext(eventos), await anext(eventos)]
        # El cliente se va: nadie vuelve a pedir un trozo.
        await eventos.aclose()
        return [json.loads(e[len("data: ") :]) for e in leidos]

    leidos = bd.run(a_medias)

    assert [e["type"] for e in leidos] == ["start", "delta"]
    # Lo que importa: la conexión con el proveedor NO quedó colgando…
    assert doble.cerrado is True
    # …y la respuesta a medias no se guardó.
    assert _mensajes(bd, conversation_id) == []


# --- Rate limiting y CORS -----------------------------------------------------


def test_la_cuota_por_usuario_aplica_al_chat(
    bd: BaseDeTest, proveedor: ProveedorDeChat, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_default_limit", 1_000)
    monkeypatch.setattr(settings, "rate_limit_user_limit", 2)
    monkeypatch.setattr(settings, "rate_limit_user_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_pro_multiplier", 1.0)
    _, token = _token()

    with TestClient(app) as client:
        codigos = [_post(client, token, message="hola").status_code for _ in range(3)]

    assert codigos == [200, 200, 429]


def test_el_429_del_chat_sale_con_cabeceras_de_cors(
    bd: BaseDeTest, proveedor: ProveedorDeChat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El rate limiting va por DENTRO de CORS (HU-1.7): el navegador debe poder leerlo.

    Sin las cabeceras de CORS en el rechazo, el JavaScript de la web vería un
    error de CORS genérico en vez de "te pasaste de peticiones", y no podría
    leer ``Retry-After`` para reintentar sola.
    """
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_default_limit", 1)
    origen = {"Origin": _ORIGEN_WEB}
    _, token = _token()

    with TestClient(app) as client:
        client.post("/v1/chat", headers={**_auth(token), **origen}, json={"message": "hola"})
        rechazo = client.post("/v1/chat", headers={**_auth(token), **origen}, json={"message": "x"})

    assert rechazo.status_code == 429
    assert rechazo.headers["access-control-allow-origin"] == _ORIGEN_WEB
    assert "Retry-After" in rechazo.headers


def test_el_preflight_de_chat_se_responde(bd: BaseDeTest) -> None:
    """El OPTIONS lo corta CORS antes del rate limiter, y no consume cupo."""
    with TestClient(app) as client:
        respuesta = client.options(
            "/v1/chat",
            headers={
                "Origin": _ORIGEN_WEB,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == _ORIGEN_WEB
    assert "POST" in respuesta.headers["access-control-allow-methods"]


# --- Título (unidad) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("mensaje", "esperado"),
    [
        ("Hola", "Hola"),
        ("  Hola   mundo \n ", "Hola mundo"),
        ("x" * 60, "x" * 60),
        ("x" * 61, "x" * 59 + "…"),
    ],
)
def test_derive_title(mensaje: str, esperado: str) -> None:
    assert chat_service.derive_title(mensaje) == esperado


def test_el_proveedor_de_chat_cumple_la_interfaz() -> None:
    """Si el doble dejara de cumplir el ``Protocol``, mypy fallaría aquí."""
    conforme: LLMProvider = ProveedorDeChat()
    assert Capability.TEXT in conforme.capabilities
