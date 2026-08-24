"""Tool-calling a través de `POST /v1/chat`: lo que sale y lo que queda (HU-2.6).

``test_tools.py`` prueba la maquinaria en aislamiento. Este módulo prueba el
recorrido COMPLETO —endpoint, SSE, base de datos— y se concentra en las dos
propiedades que no se ven mirando un 200:

1. **Los pasos intermedios quedan guardados.** Qué herramienta, con qué
   argumentos y qué devolvió, en ``messages.tool_steps`` del mensaje del
   asistente que los usó.
2. **Y no salen por ninguna parte.** Ni por el stream, ni por
   ``GET /v1/chat/sessions/{id}``. Se comprueba con un **señuelo** dentro del
   resultado de la herramienta: si esa cadena aparece en un cuerpo de la API,
   el test se pone rojo.

Sin DeepSeek y sin OpenWeatherMap: el proveedor de LLM es el doble con guion de
``test_chat.py`` y el del clima es un doble local.
"""

import json
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models import Message, MessageRole
from app.services.llm import set_llm_provider
from app.services.tools import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNKNOWN_TOOL,
    WEATHER_TOOL_NAME,
    ToolFailed,
    ToolRegistry,
    WeatherTool,
    set_tool_registry,
)
from app.services.weather import CurrentWeather, Place, WeatherUnavailable, set_weather_provider
from tests import auth_utils
from tests.conftest import BaseDeTest
from tests.test_chat import ProveedorDeChat, Vuelta, eventos_de

SESIONES = "/v1/chat/sessions"

#: Si esta frase aparece en una respuesta de la API, algo filtró los pasos
#: internos de tool-calling. Va DENTRO del resultado de la herramienta.
SEÑUELO = "SECRETO-DE-LA-HERRAMIENTA"


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_utils.install_auth_env(monkeypatch)
    # Sin key: el catálogo por defecto queda vacío y cada test instala el suyo.
    monkeypatch.setattr(settings, "weather_api_key", None)


# --- Dobles ------------------------------------------------------------------


class HerramientaConSeñuelo:
    """Devuelve un resultado que lleva el señuelo, o falla si se le pide."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.llamadas: list[Mapping[str, Any]] = []

    @property
    def name(self) -> str:
        return "buscar_algo"

    @property
    def description(self) -> str:
        return "Busca algo cuando haga falta."

    @property
    def parameters(self) -> Mapping[str, Any]:
        return {
            "type": "object",
            "properties": {"consulta": {"type": "string"}},
            "required": ["consulta"],
        }

    @property
    def status_label(self) -> str:
        return "Buscando algo…"

    async def run(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.llamadas.append(dict(arguments))
        if self._error is not None:
            raise self._error
        return {"hallazgo": SEÑUELO, "detalle": "dato interno que no debe salir"}


class ClimaDeMentira:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.consultas: list[tuple[str, str | None]] = []

    @property
    def name(self) -> str:
        return "doble"

    async def current(self, location: str, *, country_code: str | None = None) -> CurrentWeather:
        self.consultas.append((location, country_code))
        if self._error is not None:
            raise self._error
        return CurrentWeather(
            place=Place(name="Bogotá", country="CO", latitude=4.65, longitude=-74.08),
            temperature_c=14.2,
            feels_like_c=13.5,
            condition="nubes dispersas",
            humidity_pct=77,
            wind_kph=11.3,
        )


# --- Utilidades --------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> tuple[uuid.UUID, str]:
    uid = uuid.uuid4()
    return uid, auth_utils.make_token(sub=str(uid))


def _post(client: TestClient, token: str, **cuerpo: Any) -> Any:
    return client.post("/v1/chat", json=cuerpo, headers=_auth(token))


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


def _instalar(guion: list[Vuelta], herramientas: list[Any]) -> ProveedorDeChat:
    proveedor = ProveedorDeChat(guion=guion)
    set_llm_provider(proveedor)
    set_tool_registry(ToolRegistry(herramientas))
    return proveedor


def _turno(bd: BaseDeTest, guion: list[Vuelta], herramientas: list[Any]) -> tuple[Any, uuid.UUID]:
    """Hace un turno completo y devuelve (eventos, conversation_id)."""
    _instalar(guion, herramientas)
    _, token = _token()
    with TestClient(app) as client:
        respuesta = _post(client, token, message="¿qué tal el clima en Bogotá?")
    assert respuesta.status_code == 200, respuesta.text
    eventos = eventos_de(respuesta.text)
    return eventos, uuid.UUID(eventos[0]["conversation_id"])


# =============================================================================
# El ciclo completo por SSE
# =============================================================================


def test_el_ciclo_completo_llega_al_cliente_como_texto(bd: BaseDeTest) -> None:
    clima = ClimaDeMentira()
    set_weather_provider(clima)
    eventos, _ = _turno(
        bd,
        [
            Vuelta(tool_calls=[(WEATHER_TOOL_NAME, '{"location": "Bogotá"}')]),
            Vuelta(trozos=["En Bogotá hay 14 grados ", "y nubes dispersas."]),
        ],
        [WeatherTool()],
    )

    tipos = [e["type"] for e in eventos]
    assert tipos == ["start", "status", "delta", "delta", "done"]
    assert clima.consultas == [("Bogotá", None)]
    texto = "".join(e["text"] for e in eventos if e["type"] == "delta")
    assert texto == "En Bogotá hay 14 grados y nubes dispersas."


def test_el_evento_de_estado_solo_dice_QUE_se_consulta(bd: BaseDeTest) -> None:
    set_weather_provider(ClimaDeMentira())
    eventos, _ = _turno(
        bd,
        [
            Vuelta(tool_calls=[(WEATHER_TOOL_NAME, '{"location": "Bogotá"}')]),
            Vuelta(trozos=["Listo."]),
        ],
        [WeatherTool()],
    )

    (estado,) = [e for e in eventos if e["type"] == "status"]
    assert estado == {
        "type": "status",
        "tool": "get_weather",
        "message": "Consultando el clima…",
    }


def test_sin_herramientas_el_stream_es_EXACTAMENTE_el_de_antes(bd: BaseDeTest) -> None:
    """La pregunta que no las necesita responde directo, como en la HU-2.4."""
    eventos, conversation_id = _turno(
        bd, [Vuelta(trozos=["Hola, ", "soy Rover."])], [HerramientaConSeñuelo()]
    )

    assert [e["type"] for e in eventos] == ["start", "delta", "delta", "done"]
    _, asistente = _mensajes(bd, conversation_id)
    assert asistente.content == "Hola, soy Rover."
    assert asistente.tool_steps == []


# =============================================================================
# Persistencia de los pasos intermedios
# =============================================================================


def test_los_pasos_quedan_en_tool_steps_del_mensaje_del_asistente(bd: BaseDeTest) -> None:
    herramienta = HerramientaConSeñuelo()
    _, conversation_id = _turno(
        bd,
        [
            Vuelta(tool_calls=[("buscar_algo", '{"consulta": "Bogotá"}')]),
            Vuelta(trozos=["Ya lo miré."]),
        ],
        [herramienta],
    )

    usuario, asistente = _mensajes(bd, conversation_id)

    # El invariante de la HU-2.4 sigue en pie: la fila del asistente es una
    # respuesta COMPLETA, y su ``content`` es solo texto conversacional.
    assert usuario.role is MessageRole.USER
    assert usuario.tool_steps == []
    assert asistente.role is MessageRole.ASSISTANT
    assert asistente.content == "Ya lo miré."
    # Y los pasos están, con todo lo que hace falta para depurar.
    (paso,) = asistente.tool_steps
    assert paso["tool"] == "buscar_algo"
    assert paso["arguments"] == {"consulta": "Bogotá"}
    assert paso["result"]["hallazgo"] == SEÑUELO
    assert paso["status"] == STATUS_OK


def test_los_pasos_de_varias_herramientas_se_guardan_en_orden(bd: BaseDeTest) -> None:
    set_weather_provider(ClimaDeMentira())
    _, conversation_id = _turno(
        bd,
        [
            Vuelta(
                tool_calls=[
                    ("buscar_algo", '{"consulta": "a"}'),
                    (WEATHER_TOOL_NAME, '{"location": "Bogotá"}'),
                ]
            ),
            Vuelta(trozos=["Ya."]),
        ],
        [HerramientaConSeñuelo(), WeatherTool()],
    )

    _, asistente = _mensajes(bd, conversation_id)

    assert [p["tool"] for p in asistente.tool_steps] == ["buscar_algo", "get_weather"]


# =============================================================================
# Y NO se exponen: ni por el stream, ni por el historial
# =============================================================================


def test_los_pasos_NO_aparecen_en_el_stream(bd: BaseDeTest) -> None:
    """El señuelo va dentro del resultado de la herramienta: no puede salir."""
    _instalar(
        [
            Vuelta(tool_calls=[("buscar_algo", '{"consulta": "Bogotá"}')]),
            Vuelta(trozos=["Ya lo miré."]),
        ],
        [HerramientaConSeñuelo()],
    )
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="mira algo")

    assert SEÑUELO not in respuesta.text
    assert "dato interno" not in respuesta.text
    assert "tool_steps" not in respuesta.text
    # Ni siquiera los argumentos con los que se llamó.
    assert "consulta" not in respuesta.text


def test_los_pasos_NO_aparecen_en_el_historial_expuesto(bd: BaseDeTest) -> None:
    """``GET /v1/chat/sessions/{id}`` sobre pasos REALES, no sembrados a mano."""
    _instalar(
        [
            Vuelta(tool_calls=[("buscar_algo", '{"consulta": "Bogotá"}')]),
            Vuelta(trozos=["Ya lo miré."]),
        ],
        [HerramientaConSeñuelo()],
    )
    _, token = _token()

    with TestClient(app) as client:
        stream = _post(client, token, message="mira algo")
        conversation_id = eventos_de(stream.text)[0]["conversation_id"]
        historial = client.get(f"{SESIONES}/{conversation_id}", headers=_auth(token))

    assert historial.status_code == 200
    crudo = historial.text
    assert SEÑUELO not in crudo
    assert "tool_steps" not in crudo
    # Lo que sí está es la conversación, entera.
    turnos = historial.json()["messages"]
    assert [t["role"] for t in turnos] == ["user", "assistant"]
    assert turnos[1]["content"] == "Ya lo miré."
    # Y ninguna clave nueva se coló en el contrato.
    assert set(turnos[1]) == {"role", "content", "sequence", "created_at"}
    # Pero en la BASE sí están guardados: no se perdieron, se ocultaron.
    _, asistente = _mensajes(bd, uuid.UUID(conversation_id))
    assert asistente.tool_steps[0]["result"]["hallazgo"] == SEÑUELO


def test_los_pasos_NO_vuelven_al_contexto_del_turno_siguiente(bd: BaseDeTest) -> None:
    """Decisión cerrada de la HU-2.5: caducados, caros y ya resumidos en el texto."""
    _instalar(
        [
            Vuelta(tool_calls=[("buscar_algo", '{"consulta": "Bogotá"}')]),
            Vuelta(trozos=["Ya lo miré."]),
        ],
        [HerramientaConSeñuelo()],
    )
    _, token = _token()

    with TestClient(app) as client:
        primero = _post(client, token, message="mira algo")
        conversation_id = eventos_de(primero.text)[0]["conversation_id"]
        # Segundo turno: el modelo NO pide herramientas.
        segundo = ProveedorDeChat(["Claro."])
        set_llm_provider(segundo)
        _post(client, token, message="¿y qué más?", conversation_id=conversation_id)

    contexto = "\n".join(m.content for m in segundo.recibido)
    assert SEÑUELO not in contexto
    assert "buscar_algo" not in contexto
    # Lo que sí vuelve es la conclusión, que es lo que hay que recordar.
    assert "Ya lo miré." in contexto


# =============================================================================
# Degradación: la conversación nunca se cae
# =============================================================================


def test_una_herramienta_que_FALLA_deja_una_respuesta_completa(bd: BaseDeTest) -> None:
    """El usuario recibe texto y la fila del asistente sigue siendo completa."""
    eventos, conversation_id = _turno(
        bd,
        [
            Vuelta(tool_calls=[("buscar_algo", '{"consulta": "Bogotá"}')]),
            Vuelta(trozos=["No pude mirarlo ahora, ", "pero te cuento lo que sé."]),
        ],
        [HerramientaConSeñuelo(error=ToolFailed("El servicio no responde.", cause="boom"))],
    )

    assert [e["type"] for e in eventos] == ["start", "status", "delta", "delta", "done"]
    assert "error" not in [e["type"] for e in eventos]
    _, asistente = _mensajes(bd, conversation_id)
    assert asistente.content == "No pude mirarlo ahora, pero te cuento lo que sé."
    (paso,) = asistente.tool_steps
    assert paso["status"] == STATUS_ERROR
    assert paso["cause"] == "boom"


def test_el_clima_caido_no_tumba_la_conversacion(bd: BaseDeTest) -> None:
    """El caso real: la API del clima responde 401 porque la key no está activa."""
    set_weather_provider(ClimaDeMentira(error=WeatherUnavailable("caído", provider_status=401)))
    eventos, conversation_id = _turno(
        bd,
        [
            Vuelta(tool_calls=[(WEATHER_TOOL_NAME, '{"location": "Bogotá"}')]),
            Vuelta(trozos=["No pude consultar el clima, ", "pero en esta época suele llover."]),
        ],
        [WeatherTool()],
    )

    assert "error" not in [e["type"] for e in eventos]
    _, asistente = _mensajes(bd, conversation_id)
    assert asistente.tool_steps[0]["status"] == STATUS_ERROR
    # Al cliente no le llegó ni una palabra del diagnóstico.
    assert "401" not in json.dumps(eventos)


def test_una_herramienta_INEXISTENTE_no_rompe_el_turno(bd: BaseDeTest) -> None:
    eventos, conversation_id = _turno(
        bd,
        [
            Vuelta(tool_calls=[("consultar_horoscopo", "{}")]),
            Vuelta(trozos=["De eso no sé, pero…"]),
        ],
        [HerramientaConSeñuelo()],
    )

    # Sin evento de estado: no se le anuncia al usuario una alucinación.
    assert [e["type"] for e in eventos] == ["start", "delta", "done"]
    _, asistente = _mensajes(bd, conversation_id)
    assert asistente.content == "De eso no sé, pero…"
    assert asistente.tool_steps[0]["status"] == STATUS_UNKNOWN_TOOL


def test_unos_argumentos_INVALIDOS_no_rompen_el_turno(bd: BaseDeTest) -> None:
    herramienta = HerramientaConSeñuelo()
    eventos, conversation_id = _turno(
        bd,
        [
            Vuelta(tool_calls=[("buscar_algo", "{roto")]),
            Vuelta(trozos=["Vale."]),
        ],
        [herramienta],
    )

    assert "error" not in [e["type"] for e in eventos]
    assert herramienta.llamadas == []
    _, asistente = _mensajes(bd, conversation_id)
    assert asistente.tool_steps[0]["status"] == "invalid_arguments"


def test_un_modelo_que_INSISTE_acaba_respondiendo(
    bd: BaseDeTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El límite del loop corta, y la última vuelta —sin tools— sí redacta."""
    monkeypatch.setattr(settings, "tool_loop_max_iterations", 3)
    herramienta = HerramientaConSeñuelo()
    # La última vuelta del guion se repite: el doble siempre pide la herramienta
    # mientras se la ofrezcan. Lo que para es el loop.
    proveedor = _instalar(
        [
            Vuelta(tool_calls=[("buscar_algo", '{"consulta": "x"}')]),
            Vuelta(tool_calls=[("buscar_algo", '{"consulta": "x"}')]),
            Vuelta(trozos=["Me rindo, te cuento lo que sé."]),
        ],
        [herramienta],
    )
    _, token = _token()

    with TestClient(app) as client:
        respuesta = _post(client, token, message="insiste")

    eventos = eventos_de(respuesta.text)
    assert eventos[-1]["type"] == "done"
    assert proveedor.llamadas == 3
    assert len(herramienta.llamadas) == 2
    conversation_id = uuid.UUID(eventos[0]["conversation_id"])
    _, asistente = _mensajes(bd, conversation_id)
    assert asistente.content == "Me rindo, te cuento lo que sé."
    assert len(asistente.tool_steps) == 2
