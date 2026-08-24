"""Tests de la maquinaria de tool-calling (HU-2.6): registro, validación y loop.

Ni modelo ni APIs reales: el proveedor de LLM es el doble con guion de
``tests/test_chat.py`` (que emite las peticiones de herramienta **fragmentadas**,
como el real) y las herramientas son dobles locales.

Lo que se prueba aquí es el MECANISMO, no el clima: los mismos tests seguirían
valiendo con la herramienta de lugares o la de búsqueda web. La del clima tiene
su propio bloque al final, y su proveedor tiene el suyo en ``test_weather.py``.
"""

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from anyio.abc import BlockingPortal

from app.core.config import settings
from app.services.llm import Message as LLMMessage
from app.services.llm import Role as LLMRole
from app.services.tools import (
    STATUS_ERROR,
    STATUS_INVALID_ARGUMENTS,
    STATUS_OK,
    STATUS_UNKNOWN_TOOL,
    WEATHER_TOOL_NAME,
    ArgumentError,
    TextDelta,
    Tool,
    ToolFailed,
    ToolLoop,
    ToolRegistry,
    ToolStatus,
    TurnEvent,
    WeatherTool,
    get_tool_registry,
    parse_arguments,
    set_tool_registry,
)
from app.services.weather import (
    CurrentWeather,
    Place,
    WeatherNotConfigured,
    WeatherNotFound,
    WeatherUnavailable,
    set_weather_provider,
)
from tests.test_chat import ProveedorDeChat, Vuelta

PREGUNTA = [LLMMessage(role=LLMRole.USER, content="¿qué tal el clima en Bogotá?")]


# --- Dobles de herramienta ---------------------------------------------------


class HerramientaDeMentira:
    """Herramienta configurable: qué devuelve, o con qué falla."""

    def __init__(
        self,
        nombre: str = "buscar_algo",
        *,
        resultado: Mapping[str, Any] | None = None,
        error: Exception | None = None,
        esquema: Mapping[str, Any] | None = None,
    ) -> None:
        self._nombre = nombre
        self._resultado = resultado or {"dato": 42}
        self._error = error
        self._esquema = esquema or {
            "type": "object",
            "properties": {"consulta": {"type": "string"}},
            "required": ["consulta"],
        }
        self.llamadas: list[Mapping[str, Any]] = []

    @property
    def name(self) -> str:
        return self._nombre

    @property
    def description(self) -> str:
        return f"Busca {self._nombre} cuando haga falta."

    @property
    def parameters(self) -> Mapping[str, Any]:
        return self._esquema

    @property
    def status_label(self) -> str:
        return f"Consultando {self._nombre}…"

    async def run(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.llamadas.append(dict(arguments))
        if self._error is not None:
            raise self._error
        return self._resultado


class ProveedorDeClimaDeMentira:
    """Doble del proveedor de clima: devuelve un dato fijo o levanta."""

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


def _ejecutar(
    portal: BlockingPortal, loop: ToolLoop, mensajes: Sequence[LLMMessage] = ()
) -> list[TurnEvent]:
    """Agota el turno y devuelve todos sus eventos."""

    async def correr() -> list[TurnEvent]:
        return [evento async for evento in loop.run(list(mensajes) or PREGUNTA)]

    return portal.call(correr)


def _texto(eventos: Sequence[TurnEvent]) -> str:
    return "".join(e.text for e in eventos if isinstance(e, TextDelta))


def _estados(eventos: Sequence[TurnEvent]) -> list[ToolStatus]:
    return [e for e in eventos if isinstance(e, ToolStatus)]


def _mensajes_de_tool(proveedor: ProveedorDeChat, vuelta: int) -> list[LLMMessage]:
    """Los mensajes de rol ``tool`` que vio el modelo en esa vuelta (1-based)."""
    return [m for m in proveedor.contextos[vuelta - 1] if m.role is LLMRole.TOOL]


# =============================================================================
# El registro
# =============================================================================


def test_las_declaraciones_van_ordenadas_por_nombre() -> None:
    """El orden es parte del prefijo estable: no puede depender de la inserción."""
    registro = ToolRegistry(
        [HerramientaDeMentira("zeta"), HerramientaDeMentira("alfa"), HerramientaDeMentira("media")]
    )

    assert [spec.name for spec in registro.specs()] == ["alfa", "media", "zeta"]


def test_la_declaracion_lleva_nombre_descripcion_y_esquema() -> None:
    registro = ToolRegistry([HerramientaDeMentira("buscar")])

    (spec,) = registro.specs()

    assert spec.name == "buscar"
    assert "Busca buscar" in spec.description
    assert spec.parameters["type"] == "object"
    assert spec.parameters["required"] == ["consulta"]


def test_registrar_dos_veces_el_mismo_nombre_es_un_error() -> None:
    """Si no, el modelo pediría una y se ejecutaría otra — sin que nada fallara."""
    registro = ToolRegistry([HerramientaDeMentira("buscar")])

    with pytest.raises(ValueError, match="buscar"):
        registro.register(HerramientaDeMentira("buscar"))


def test_una_herramienta_desconocida_devuelve_None_y_no_levanta() -> None:
    """Que el modelo se invente un nombre es lo NORMAL, no una anomalía."""
    registro = ToolRegistry([HerramientaDeMentira("buscar")])

    assert registro.get("inventada") is None
    assert registro.get("buscar") is not None
    assert registro.names() == ("buscar",)


def test_el_catalogo_por_defecto_trae_el_clima_cuando_hay_con_que(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "weather_api_key", None)
    set_weather_provider(ProveedorDeClimaDeMentira())

    assert [spec.name for spec in get_tool_registry().specs()] == [WEATHER_TOOL_NAME]


def test_sin_clima_configurado_la_herramienta_NI_SE_OFRECE(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Ofrecer algo que solo puede fallar cuesta tokens y enseña a prometerlo."""
    monkeypatch.setattr(settings, "weather_api_key", None)

    with caplog.at_level(logging.WARNING, logger="app.services.tools.registry"):
        registro = get_tool_registry()

    assert len(registro) == 0
    assert "ROVER_WEATHER_API_KEY" in "\n".join(r.getMessage() for r in caplog.records)


# =============================================================================
# Validación de los argumentos que manda el modelo
# =============================================================================


ESQUEMA = {
    "type": "object",
    "properties": {"location": {"type": "string"}, "dias": {"type": "integer"}},
    "required": ["location"],
}


def test_parsea_los_argumentos_bien_formados() -> None:
    assert parse_arguments('{"location": "Bogotá"}', ESQUEMA) == {"location": "Bogotá"}


def test_una_cadena_vacia_equivale_a_sin_argumentos() -> None:
    """Es lo que emiten varios proveedores para una tool sin obligatorios."""
    assert parse_arguments("", {"type": "object", "properties": {}}) == {}


@pytest.mark.parametrize(
    "crudos",
    ['{"location": "Bogotá"', "no soy json", '"solo una cadena"', "[1, 2, 3]", "42"],
)
def test_lo_que_no_es_un_objeto_json_se_rechaza_con_un_motivo(crudos: str) -> None:
    with pytest.raises(ArgumentError) as exc:
        parse_arguments(crudos, ESQUEMA)

    # El mensaje es para el MODELO: tiene que decirle qué hacer distinto.
    assert "JSON" in str(exc.value)


def test_faltar_un_obligatorio_dice_CUAL_falta() -> None:
    with pytest.raises(ArgumentError, match="'location'"):
        parse_arguments('{"dias": 3}', ESQUEMA)


def test_un_tipo_equivocado_dice_cual_se_esperaba() -> None:
    with pytest.raises(ArgumentError, match="integer"):
        parse_arguments('{"location": "Bogotá", "dias": "tres"}', ESQUEMA)


def test_un_booleano_no_cuela_como_numero() -> None:
    """En Python ``bool`` es ``int``; un ``true`` donde va un entero es un error."""
    with pytest.raises(ArgumentError, match="integer"):
        parse_arguments('{"location": "Bogotá", "dias": true}', ESQUEMA)


def test_los_campos_de_mas_se_ignoran_en_vez_de_romper() -> None:
    """Romper por generosidad gastaría una vuelta entera del loop para nada."""
    assert parse_arguments('{"location": "Bogotá", "unidad": "C"}', ESQUEMA) == {
        "location": "Bogotá",
        "unidad": "C",
    }


def test_un_opcional_nulo_equivale_a_no_mandarlo() -> None:
    assert parse_arguments('{"location": "Bogotá", "dias": null}', ESQUEMA) == {
        "location": "Bogotá",
        "dias": None,
    }


# =============================================================================
# El loop
# =============================================================================


def test_cero_herramientas_responde_directo(loop_de_test: BlockingPortal) -> None:
    """El camino de la mayoría de los turnos: igual que antes de esta HU."""
    proveedor = ProveedorDeChat(["Medellín ", "es una gran idea."])
    loop = ToolLoop(proveedor, registry=ToolRegistry([HerramientaDeMentira()]))

    eventos = _ejecutar(loop_de_test, loop)

    assert _texto(eventos) == "Medellín es una gran idea."
    assert _estados(eventos) == []
    assert proveedor.llamadas == 1
    assert loop.steps == []
    assert loop.used_tools is False


def test_el_ciclo_completo_de_UNA_herramienta(loop_de_test: BlockingPortal) -> None:
    """Pide → se ejecuta → el resultado vuelve al modelo → redacta. En streaming."""
    herramienta = HerramientaDeMentira("buscar", resultado={"dato": "encontrado"})
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("buscar", '{"consulta": "algo"}')]),
            Vuelta(trozos=["Encontré ", "esto."]),
        ]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([herramienta]))

    eventos = _ejecutar(loop_de_test, loop)

    # 1. La herramienta se ejecutó con los argumentos que pidió el modelo.
    assert herramienta.llamadas == [{"consulta": "algo"}]
    # 2. El resultado volvió al modelo como un mensaje de rol ``tool``.
    (resultado,) = _mensajes_de_tool(proveedor, vuelta=2)
    assert json.loads(resultado.content) == {"dato": "encontrado"}
    assert resultado.tool_call_id == "call_0"
    # 3. Y el turno del asistente que PIDIÓ también viaja, con sus tool_calls:
    #    sin él el proveedor devolvería 400.
    pidio = proveedor.contextos[1][-2]
    assert pidio.role is LLMRole.ASSISTANT
    assert [c.name for c in pidio.tool_calls] == ["buscar"]
    # 4. El texto final salió por el stream.
    assert _texto(eventos) == "Encontré esto."
    assert proveedor.llamadas == 2


def test_varias_herramientas_en_la_MISMA_vuelta(loop_de_test: BlockingPortal) -> None:
    """Cada resultado vuelve con el id de SU petición: es lo único que las distingue."""
    una = HerramientaDeMentira("una", resultado={"cual": 1})
    otra = HerramientaDeMentira("otra", resultado={"cual": 2})
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("una", '{"consulta": "a"}'), ("otra", '{"consulta": "b"}')]),
            Vuelta(trozos=["Listo."]),
        ]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([una, otra]))

    eventos = _ejecutar(loop_de_test, loop)

    assert una.llamadas == [{"consulta": "a"}]
    assert otra.llamadas == [{"consulta": "b"}]
    resultados = _mensajes_de_tool(proveedor, vuelta=2)
    assert [m.tool_call_id for m in resultados] == ["call_0", "call_1"]
    assert [json.loads(m.content)["cual"] for m in resultados] == [1, 2]
    assert [e.tool for e in _estados(eventos)] == ["una", "otra"]
    assert [p["tool"] for p in loop.steps] == ["una", "otra"]


def test_herramientas_encadenadas_en_vueltas_distintas(loop_de_test: BlockingPortal) -> None:
    una = HerramientaDeMentira("una")
    otra = HerramientaDeMentira("otra")
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("una", '{"consulta": "a"}')]),
            Vuelta(tool_calls=[("otra", '{"consulta": "b"}')]),
            Vuelta(trozos=["Ya."]),
        ]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([una, otra]), max_iterations=4)

    _ejecutar(loop_de_test, loop)

    assert [p["tool"] for p in loop.steps] == ["una", "otra"]
    assert [p["iteration"] for p in loop.steps] == [1, 2]
    assert proveedor.llamadas == 3


def test_el_preambulo_antes_de_llamar_tambien_se_transmite(
    loop_de_test: BlockingPortal,
) -> None:
    """El modelo puede escribir una frase Y pedir una herramienta en la misma vuelta."""
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(trozos=["Déjame mirar. "], tool_calls=[("buscar", '{"consulta": "x"}')]),
            Vuelta(trozos=["Ya está."]),
        ]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([HerramientaDeMentira("buscar")]))

    eventos = _ejecutar(loop_de_test, loop)

    assert _texto(eventos) == "Déjame mirar. Ya está."


def test_las_herramientas_se_ofrecen_en_todas_las_vueltas_menos_la_ultima(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor = ProveedorDeChat(
        guion=[Vuelta(tool_calls=[("buscar", '{"consulta": "x"}')]), Vuelta(trozos=["Ya."])]
    )
    loop = ToolLoop(
        proveedor, registry=ToolRegistry([HerramientaDeMentira("buscar")]), max_iterations=3
    )

    _ejecutar(loop_de_test, loop)

    assert proveedor.tools_ofrecidas == [("buscar",), ("buscar",)]


# --- El límite de vueltas ----------------------------------------------------


def test_el_limite_corta_a_un_modelo_que_INSISTE(
    loop_de_test: BlockingPortal, caplog: pytest.LogCaptureFixture
) -> None:
    """El doble repite su última vuelta para siempre: lo que para es el límite."""
    herramienta = HerramientaDeMentira("buscar")
    # Guion de UNA vuelta que siempre pide la herramienta.
    proveedor = ProveedorDeChat(guion=[Vuelta(tool_calls=[("buscar", '{"consulta": "x"}')])])
    loop = ToolLoop(proveedor, registry=ToolRegistry([herramienta]), max_iterations=3)

    with caplog.at_level(logging.WARNING, logger="app.services.tools.loop"):
        _ejecutar(loop_de_test, loop)

    # 3 llamadas al modelo, 2 ejecuciones (la última vuelta no ofrece tools).
    assert proveedor.llamadas == 3
    assert len(herramienta.llamadas) == 2
    assert "límite" in "\n".join(r.getMessage() for r in caplog.records)


def test_al_llegar_al_limite_la_ultima_llamada_va_SIN_herramientas(
    loop_de_test: BlockingPortal,
) -> None:
    """Así el turno acaba en una respuesta escrita, no en un error."""
    proveedor = ProveedorDeChat(guion=[Vuelta(tool_calls=[("buscar", '{"consulta": "x"}')])])
    loop = ToolLoop(
        proveedor, registry=ToolRegistry([HerramientaDeMentira("buscar")]), max_iterations=2
    )

    _ejecutar(loop_de_test, loop)

    assert proveedor.tools_ofrecidas == [("buscar",), ()]


def test_el_limite_sale_de_la_configuracion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tool_loop_max_iterations", 7)
    loop = ToolLoop(ProveedorDeChat(), registry=ToolRegistry())

    assert loop._max_iterations == 7


# --- Degradación: los cuatro caminos de fallo --------------------------------


def test_una_herramienta_INEXISTENTE_no_rompe_el_turno(
    loop_de_test: BlockingPortal, caplog: pytest.LogCaptureFixture
) -> None:
    """El fallo típico del tool-calling: el modelo se inventa el nombre."""
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("consultar_horoscopo", "{}")]),
            Vuelta(trozos=["Eso no lo sé, pero…"]),
        ]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([HerramientaDeMentira("buscar")]))

    with caplog.at_level(logging.WARNING, logger="app.services.tools.loop"):
        eventos = _ejecutar(loop_de_test, loop)

    assert _texto(eventos) == "Eso no lo sé, pero…"
    # Se le contesta igual, con la lista de las que SÍ existen.
    (respuesta,) = _mensajes_de_tool(proveedor, vuelta=2)
    assert "no existe" in json.loads(respuesta.content)["error"].lower()
    assert "buscar" in json.loads(respuesta.content)["error"]
    assert loop.steps[0]["status"] == STATUS_UNKNOWN_TOOL
    # Y NO se le anuncia al usuario una capacidad que no existe.
    assert _estados(eventos) == []
    assert "consultar_horoscopo" in "\n".join(r.getMessage() for r in caplog.records)


def test_unos_argumentos_INVALIDOS_no_rompen_el_turno(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("buscar", "{esto no es json")]),
            Vuelta(trozos=["Vale."]),
        ]
    )
    herramienta = HerramientaDeMentira("buscar")
    loop = ToolLoop(proveedor, registry=ToolRegistry([herramienta]))

    eventos = _ejecutar(loop_de_test, loop)

    assert _texto(eventos) == "Vale."
    assert herramienta.llamadas == []  # no se llegó a ejecutar
    (respuesta,) = _mensajes_de_tool(proveedor, vuelta=2)
    assert "JSON" in json.loads(respuesta.content)["error"]
    paso = loop.steps[0]
    assert paso["status"] == STATUS_INVALID_ARGUMENTS
    # Los argumentos crudos quedan en el paso: es lo que hace falta para
    # reproducir el fallo, y es interno.
    assert paso["raw_arguments"] == "{esto no es json"


def test_una_herramienta_que_FALLA_no_tumba_la_conversacion(
    loop_de_test: BlockingPortal, caplog: pytest.LogCaptureFixture
) -> None:
    """El error se le devuelve al MODELO para que responda con gracia."""
    herramienta = HerramientaDeMentira(
        "buscar", error=ToolFailed("El servicio no responde.", cause="ConnectError: sin ruta")
    )
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("buscar", '{"consulta": "x"}')]),
            Vuelta(trozos=["No pude mirarlo, ", "pero te cuento lo que sé."]),
        ]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([herramienta]))

    with caplog.at_level(logging.WARNING, logger="app.services.tools.loop"):
        eventos = _ejecutar(loop_de_test, loop)

    assert _texto(eventos) == "No pude mirarlo, pero te cuento lo que sé."
    (respuesta,) = _mensajes_de_tool(proveedor, vuelta=2)
    assert json.loads(respuesta.content) == {"error": "El servicio no responde."}
    paso = loop.steps[0]
    assert paso["status"] == STATUS_ERROR
    # La causa REAL queda en el paso y en el log; al modelo no le llega.
    assert paso["cause"] == "ConnectError: sin ruta"
    assert "sin ruta" in "\n".join(r.getMessage() for r in caplog.records)
    assert "sin ruta" not in respuesta.content


def test_un_bug_de_la_herramienta_tampoco_tumba_la_conversacion(
    loop_de_test: BlockingPortal, caplog: pytest.LogCaptureFixture
) -> None:
    """Una excepción no prevista se degrada igual, pero se loguea CON traza."""
    herramienta = HerramientaDeMentira("buscar", error=ZeroDivisionError("boom"))
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("buscar", '{"consulta": "x"}')]),
            Vuelta(trozos=["Sigo aquí."]),
        ]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([herramienta]))

    with caplog.at_level(logging.ERROR, logger="app.services.tools.loop"):
        eventos = _ejecutar(loop_de_test, loop)

    assert _texto(eventos) == "Sigo aquí."
    assert loop.steps[0]["status"] == STATUS_ERROR
    assert "ZeroDivisionError" in loop.steps[0]["cause"]
    (registro,) = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert registro.exc_info is not None  # la traza, porque hay algo que arreglar


def test_TODA_peticion_se_contesta_aunque_alguna_falle(
    loop_de_test: BlockingPortal,
) -> None:
    """El formato de cable lo exige: una sin contestar y el proveedor da 400."""
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(
                tool_calls=[
                    ("buscar", '{"consulta": "a"}'),
                    ("inventada", "{}"),
                    ("rota", '{"consulta": "c"}'),
                ]
            ),
            Vuelta(trozos=["Ya."]),
        ]
    )
    registro = ToolRegistry(
        [HerramientaDeMentira("buscar"), HerramientaDeMentira("rota", error=ToolFailed("no"))]
    )
    loop = ToolLoop(proveedor, registry=registro)

    _ejecutar(loop_de_test, loop)

    respuestas = _mensajes_de_tool(proveedor, vuelta=2)
    assert [m.tool_call_id for m in respuestas] == ["call_0", "call_1", "call_2"]
    assert [p["status"] for p in loop.steps] == [STATUS_OK, STATUS_UNKNOWN_TOOL, STATUS_ERROR]


# --- Los pasos intermedios ---------------------------------------------------


def test_el_paso_guarda_herramienta_argumentos_resultado_y_duracion(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("buscar", '{"consulta": "Bogotá"}')]),
            Vuelta(trozos=["Listo."]),
        ]
    )
    loop = ToolLoop(
        proveedor,
        registry=ToolRegistry([HerramientaDeMentira("buscar", resultado={"dato": "ok"})]),
    )

    _ejecutar(loop_de_test, loop)

    (paso,) = loop.steps
    assert paso["tool"] == "buscar"
    assert paso["arguments"] == {"consulta": "Bogotá"}
    assert paso["result"] == {"dato": "ok"}
    assert paso["status"] == STATUS_OK
    assert paso["iteration"] == 1
    assert paso["duration_ms"] >= 0
    # Serializable tal cual: va a una columna JSONB.
    assert json.loads(json.dumps(loop.steps)) == loop.steps


def test_se_emite_una_linea_de_instrumentacion_por_ejecucion(
    loop_de_test: BlockingPortal, caplog: pytest.LogCaptureFixture
) -> None:
    """Serie agregable (``app.tools``), sin una palabra de la conversación."""
    proveedor = ProveedorDeChat(
        guion=[Vuelta(tool_calls=[("buscar", '{"consulta": "secreto"}')]), Vuelta(trozos=["ok"])]
    )
    loop = ToolLoop(proveedor, registry=ToolRegistry([HerramientaDeMentira("buscar")]))

    with caplog.at_level(logging.INFO, logger="app.tools"):
        _ejecutar(loop_de_test, loop)

    (registro,) = [r for r in caplog.records if r.name == "app.tools"]
    assert registro.tool_name == "buscar"  # type: ignore[attr-defined]
    assert registro.tool_status == STATUS_OK  # type: ignore[attr-defined]
    assert "secreto" not in registro.getMessage()


# --- El evento de estado -----------------------------------------------------


def test_el_estado_lleva_nombre_y_frase_y_NADA_mas(loop_de_test: BlockingPortal) -> None:
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("buscar", '{"consulta": "algo privado"}')]),
            Vuelta(trozos=["ok"]),
        ]
    )
    loop = ToolLoop(
        proveedor,
        registry=ToolRegistry([HerramientaDeMentira("buscar", resultado={"secreto": "no salir"})]),
    )

    eventos = _ejecutar(loop_de_test, loop)

    (estado,) = _estados(eventos)
    assert estado.tool == "buscar"
    assert estado.label == "Consultando buscar…"
    # Ni argumentos ni resultado, por construcción: el tipo solo tiene dos campos.
    assert set(ToolStatus.__slots__) == {"tool", "label"}


# =============================================================================
# La herramienta del clima
# =============================================================================


def test_la_herramienta_del_clima_cumple_el_contrato() -> None:
    herramienta: Tool = WeatherTool()

    assert herramienta.name == "get_weather"
    assert herramienta.parameters["required"] == ["location"]
    assert "country_code" in herramienta.parameters["properties"]
    # La descripción dice el LÍMITE, que es lo que evita que prometa pronóstico.
    assert "no un pronóstico" in herramienta.description.lower()
    assert isinstance(herramienta, Tool)


def test_el_clima_devuelve_un_resultado_estructurado_y_limpio(
    loop_de_test: BlockingPortal,
) -> None:
    """Claves con la unidad DENTRO del nombre, y nada del JSON crudo."""
    set_weather_provider(ProveedorDeClimaDeMentira())

    resultado = loop_de_test.call(lambda: WeatherTool().run({"location": "Bogotá"}))

    assert resultado == {
        "location": "Bogotá, CO",
        "temperature_c": 14.2,
        "feels_like_c": 13.5,
        "condition": "nubes dispersas",
        "humidity_pct": 77,
        "wind_kph": 11.3,
    }


def test_el_codigo_de_pais_llega_al_proveedor(loop_de_test: BlockingPortal) -> None:
    proveedor = ProveedorDeClimaDeMentira()
    set_weather_provider(proveedor)

    loop_de_test.call(lambda: WeatherTool().run({"location": "Cali", "country_code": "CO"}))

    assert proveedor.consultas == [("Cali", "CO")]


def test_un_codigo_de_pais_en_blanco_se_ignora(loop_de_test: BlockingPortal) -> None:
    proveedor = ProveedorDeClimaDeMentira()
    set_weather_provider(proveedor)

    loop_de_test.call(lambda: WeatherTool().run({"location": "Cali", "country_code": "  "}))

    assert proveedor.consultas == [("Cali", None)]


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (WeatherNotFound("nada"), "no encontré"),
        (WeatherUnavailable("caído"), "no está disponible"),
        (WeatherNotConfigured("sin key"), "no está disponible"),
    ],
)
def test_los_errores_del_proveedor_se_traducen_a_ToolFailed(
    loop_de_test: BlockingPortal, error: Exception, esperado: str
) -> None:
    """Mensajes DISTINTOS: llevan a conversaciones distintas."""
    set_weather_provider(ProveedorDeClimaDeMentira(error=error))

    with pytest.raises(ToolFailed) as exc:
        loop_de_test.call(lambda: WeatherTool().run({"location": "Bogotá"}))

    assert esperado in str(exc.value).lower()
    # La causa técnica va aparte, para el log y el paso persistido.
    assert exc.value.cause is not None


def test_el_ciclo_completo_con_el_clima(loop_de_test: BlockingPortal) -> None:
    """La maquinaria y la primera herramienta, juntas, sin red."""
    clima = ProveedorDeClimaDeMentira()
    set_weather_provider(clima)
    set_tool_registry(ToolRegistry([WeatherTool()]))
    proveedor = ProveedorDeChat(
        guion=[
            Vuelta(tool_calls=[("get_weather", '{"location": "Bogotá"}')]),
            Vuelta(trozos=["En Bogotá hay 14 grados ", "y nubes dispersas."]),
        ]
    )
    loop = ToolLoop(proveedor, registry=get_tool_registry())

    eventos = _ejecutar(loop_de_test, loop)

    assert clima.consultas == [("Bogotá", None)]
    assert _texto(eventos) == "En Bogotá hay 14 grados y nubes dispersas."
    assert [e.label for e in _estados(eventos)] == ["Consultando el clima…"]
    assert loop.steps[0]["result"]["temperature_c"] == 14.2
