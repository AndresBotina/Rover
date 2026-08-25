"""Tests del proveedor de clima (HU-2.6). NUNCA llaman a OpenWeatherMap.

El proveedor se ejerce por ENTERO contra un ``httpx.MockTransport``: se prueba
el camino real —los dos GET encadenados, la query que se manda, el parseo, la
conversión de unidades y la traducción de errores— con respuestas escritas a
mano con la forma que devuelve la API. Un mock del método ``current`` no
probaría nada de eso.

Lo que estos tests vigilan de verdad es la **frontera de la abstracción**: que
de ``OpenWeatherMapProvider`` no salga nada con forma de OpenWeatherMap, porque
es lo que hace que cambiar a Open-Meteo sea escribir otra clase.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from anyio.abc import BlockingPortal

from app.core.config import settings
from app.services.weather import (
    CurrentWeather,
    WeatherError,
    WeatherNotConfigured,
    WeatherNotFound,
    WeatherProvider,
    WeatherUnavailable,
    get_weather_provider,
    is_weather_configured,
    reset_weather_provider,
    set_weather_provider,
)
from app.services.weather.openweathermap import PROVIDER_NAME, OpenWeatherMapProvider

API_KEY = "clave-de-clima-de-mentira-que-no-debe-aparecer-en-ningun-log"

#: Respuesta del geocoding con la forma real: una LISTA, con ``local_names``.
GEO_BOGOTA: list[dict[str, Any]] = [
    {
        "name": "Bogota",
        "local_names": {"es": "Bogotá", "en": "Bogota"},
        "lat": 4.6533326,
        "lon": -74.083652,
        "country": "CO",
        "state": "Bogota D.C.",
    }
]

#: Respuesta del clima, recortada a lo que el parseo mira más un poco de ruido
#: (los campos que NO deben salir del proveedor).
CLIMA_BOGOTA: dict[str, Any] = {
    "coord": {"lon": -74.0836, "lat": 4.6533},
    "weather": [{"id": 802, "main": "Clouds", "description": "nubes dispersas", "icon": "03d"}],
    "base": "stations",
    "main": {
        "temp": 14.23,
        "feels_like": 13.51,
        "temp_min": 13.9,
        "humidity": 77,
        "pressure": 1024,
    },
    "visibility": 10000,
    "wind": {"speed": 3.13, "deg": 120},
    "dt": 1_755_000_000,
    "sys": {"country": "CO", "sunrise": 1_754_990_000},
    "id": 3688689,
    "name": "Bogota",
    "cod": 200,
}


# --- Utilidades --------------------------------------------------------------


class Grabadora:
    """Guarda las peticiones que salieron, para poder afirmar sobre la query."""

    def __init__(self) -> None:
        self.peticiones: list[httpx.Request] = []

    def rutas(self) -> list[str]:
        return [str(p.url.path) for p in self.peticiones]


#: Un handler de ``httpx.MockTransport``: petición → respuesta escrita a mano.
Handler = Callable[[httpx.Request], httpx.Response]


def _proveedor(
    handler: Handler, *, language: str = "es"
) -> tuple[OpenWeatherMapProvider, Grabadora]:
    grabadora = Grabadora()

    def envoltorio(request: httpx.Request) -> httpx.Response:
        grabadora.peticiones.append(request)
        return handler(request)

    proveedor = OpenWeatherMapProvider(
        api_key=API_KEY,
        base_url="https://clima.de-mentira",
        language=language,
        transport=httpx.MockTransport(envoltorio),
    )
    return proveedor, grabadora


def _camino_feliz(*, geo: Any = None, clima: dict[str, Any] | None = None) -> Handler:
    """Handler que responde al geocoding y al clima según la ruta pedida."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/geo/" in request.url.path:
            return httpx.Response(200, json=GEO_BOGOTA if geo is None else geo)
        return httpx.Response(200, json=CLIMA_BOGOTA if clima is None else clima)

    return handler


def _consultar(
    portal: BlockingPortal, proveedor: WeatherProvider, lugar: str = "Bogotá", **kwargs: Any
) -> CurrentWeather:
    return portal.call(lambda: proveedor.current(lugar, **kwargs))


# --- Camino feliz ------------------------------------------------------------


def test_geocodifica_y_luego_pide_el_clima(loop_de_test: BlockingPortal) -> None:
    """Los dos pasos ocurren DENTRO del proveedor: el llamador pasa un nombre."""
    proveedor, grabadora = _proveedor(_camino_feliz())

    clima = _consultar(loop_de_test, proveedor)

    assert grabadora.rutas() == ["/geo/1.0/direct", "/data/2.5/weather"]
    assert clima.place.label == "Bogotá, CO"
    assert clima.temperature_c == 14.2
    assert clima.condition == "nubes dispersas"


def test_el_resultado_esta_en_unidades_del_dominio(loop_de_test: BlockingPortal) -> None:
    """Celsius y km/h, no lo que devuelva el proveedor.

    El viento llega en m/s cuando se piden unidades métricas; que salga en km/h
    es parte del CONTRATO, no una preferencia de presentación.
    """
    proveedor, _ = _proveedor(_camino_feliz())

    clima = _consultar(loop_de_test, proveedor)

    assert clima.wind_kph == pytest.approx(11.3)  # 3.13 m/s
    assert clima.feels_like_c == 13.5
    assert clima.humidity_pct == 77
    assert clima.observed_at is not None
    assert clima.observed_at.tzinfo is not None


@pytest.mark.parametrize(
    ("metros_por_segundo", "kilometros_por_hora"),
    [
        # El valor del falso positivo que motivó estos tests: alguien comparó
        # este m/s (de un punto) con los km/h de Rover (de otro punto) y dedujo
        # un factor de 4,77 que ningún código aplica. Queda clavado aquí para
        # que la pregunta "¿cuánto sale de 5,66?" tenga UNA respuesta en el repo.
        (5.66, 20.4),
        (7.6, 27.4),
        (3.13, 11.3),
        (1.0, 3.6),
        (0.0, 0.0),
        # 5,66 en OTRAS unidades, para que el test falle si alguna vez se
        # interpretara mal la entrada: nudos → 10,5; mph → 9,1. Ninguno es 20,4.
        (10.0, 36.0),
    ],
)
def test_el_viento_se_convierte_de_m_s_a_km_h(
    loop_de_test: BlockingPortal, metros_por_segundo: float, kilometros_por_hora: float
) -> None:
    """``wind_kph = wind.speed × 3.6``, y ningún otro factor.

    Es la conversión más fácil de romper sin que se note: cualquier número
    plausible en km/h pasa la vista, así que el único control real es fijarla
    contra valores calculados a mano.
    """
    clima = dict(CLIMA_BOGOTA, wind={"speed": metros_por_segundo, "deg": 120})
    proveedor, _ = _proveedor(_camino_feliz(clima=clima))

    assert _consultar(loop_de_test, proveedor).wind_kph == pytest.approx(kilometros_por_hora)


def test_el_viento_se_redondea_a_una_decima(loop_de_test: BlockingPortal) -> None:
    """Al modelo no se le manda un número con seis decimales.

    5,66 × 3,6 son 20,376 exactos: lo que viaja es 20,4. La precisión que sobra
    solo gasta tokens y le da al modelo una falsa sensación de exactitud sobre
    un dato que ya es una estimación de una estación cercana.
    """
    clima = dict(CLIMA_BOGOTA, wind={"speed": 5.66})
    proveedor, _ = _proveedor(_camino_feliz(clima=clima))

    assert _consultar(loop_de_test, proveedor).wind_kph == 20.4


def test_un_viento_ausente_no_revienta_ni_inventa(loop_de_test: BlockingPortal) -> None:
    """Sin ``wind`` en el cuerpo, 0 km/h — no un ``KeyError`` en una conversación."""
    sin_viento = {k: v for k, v in CLIMA_BOGOTA.items() if k != "wind"}
    proveedor, _ = _proveedor(_camino_feliz(clima=sin_viento))

    assert _consultar(loop_de_test, proveedor).wind_kph == 0.0


def test_las_demas_magnitudes_pasan_SIN_convertir(loop_de_test: BlockingPortal) -> None:
    """Temperatura, sensación y humedad ya vienen en las unidades del dominio.

    Con ``units=metric`` el proveedor entrega Celsius y porcentaje, así que lo
    único que se les hace es redondear. Este test existe para dejar por escrito
    que **no hay** aritmética escondida ahí: el fallo que se buscaba en el
    viento habría sido invisible en la temperatura, donde 16,6 y 16,2 son
    igual de creíbles.
    """
    clima = dict(CLIMA_BOGOTA, main={"temp": 16.59, "feels_like": 15.94, "humidity": 61})
    proveedor, _ = _proveedor(_camino_feliz(clima=clima))

    resultado = _consultar(loop_de_test, proveedor)

    assert resultado.temperature_c == 16.6
    assert resultado.feels_like_c == 15.9
    assert resultado.humidity_pct == 61


def test_sin_feels_like_se_cae_a_la_temperatura(loop_de_test: BlockingPortal) -> None:
    """No se inventa una sensación térmica: se repite la temperatura real."""
    clima = dict(CLIMA_BOGOTA, main={"temp": 16.59, "humidity": 61})
    proveedor, _ = _proveedor(_camino_feliz(clima=clima))

    assert _consultar(loop_de_test, proveedor).feels_like_c == 16.6


def test_la_key_y_las_unidades_viajan_en_TODAS_las_peticiones(
    loop_de_test: BlockingPortal,
) -> None:
    proveedor, grabadora = _proveedor(_camino_feliz())

    _consultar(loop_de_test, proveedor)

    for peticion in grabadora.peticiones:
        assert peticion.url.params["appid"] == API_KEY
    clima = grabadora.peticiones[1].url.params
    # ``units`` decide en qué unidades LLEGA el cuerpo, así que perderlo
    # cambiaría el significado de dos campos sin que nada fallara:
    #   - sin ``units``  → ``main.temp`` en KELVIN (289 en vez de 16);
    #   - ``imperial``   → ``wind.speed`` en MPH, y la conversión × 3.6 daría
    #                      un número un 61 % alto que seguiría pareciendo viento.
    # El de temperatura se vería enseguida; el de viento, no. De ahí el test.
    assert clima["units"] == "metric"
    assert clima["lang"] == "es"
    assert clima["lat"] == "4.6533326"


def test_usa_el_nombre_LOCAL_del_lugar_cuando_existe(loop_de_test: BlockingPortal) -> None:
    """ "Bogotá", no "Bogota": el modelo repite el nombre que le demos."""
    proveedor, _ = _proveedor(_camino_feliz())
    assert _consultar(loop_de_test, proveedor).place.name == "Bogotá"

    en_ingles, _ = _proveedor(_camino_feliz(), language="en")
    assert _consultar(loop_de_test, en_ingles).place.name == "Bogota"


def test_sin_nombre_local_cae_al_nombre_por_defecto(loop_de_test: BlockingPortal) -> None:
    geo = [{"name": "Chapinero", "lat": 4.6, "lon": -74.0, "country": "CO"}]
    proveedor, _ = _proveedor(_camino_feliz(geo=geo))

    assert _consultar(loop_de_test, proveedor).place.name == "Chapinero"


def test_el_codigo_de_pais_desambigua_la_busqueda(loop_de_test: BlockingPortal) -> None:
    proveedor, grabadora = _proveedor(_camino_feliz())

    _consultar(loop_de_test, proveedor, "Cali", country_code="CO")

    assert grabadora.peticiones[0].url.params["q"] == "Cali,CO"


def test_el_nombre_se_normaliza_antes_de_buscarlo(loop_de_test: BlockingPortal) -> None:
    """El texto lo escribe un modelo: llega con espacios y saltos de más."""
    proveedor, grabadora = _proveedor(_camino_feliz())

    _consultar(loop_de_test, proveedor, "  Ciudad   de\n México ")

    assert grabadora.peticiones[0].url.params["q"] == "Ciudad de México"


def test_el_instante_de_observacion_es_opcional(loop_de_test: BlockingPortal) -> None:
    sin_dt = {k: v for k, v in CLIMA_BOGOTA.items() if k != "dt"}
    proveedor, _ = _proveedor(_camino_feliz(clima=sin_dt))

    assert _consultar(loop_de_test, proveedor).observed_at is None


# --- La frontera de la abstracción -------------------------------------------


def test_no_sale_nada_con_forma_de_OpenWeatherMap(loop_de_test: BlockingPortal) -> None:
    """La prueba de que el cambio de proveedor es local.

    El cuerpo real trae ``cod``, ``base``, ``sys``, ``icon``, ``id``… Si algo de
    eso saliera del proveedor, quien lo consumiera acabaría dependiendo de la
    forma de OpenWeatherMap y el cambio a Open-Meteo dejaría de ser una clase.
    """
    proveedor, _ = _proveedor(_camino_feliz())

    clima = _consultar(loop_de_test, proveedor)

    campos = set(vars(CurrentWeather).get("__slots__", ()))
    assert campos == {
        "place",
        "temperature_c",
        "feels_like_c",
        "condition",
        "humidity_pct",
        "wind_kph",
        "observed_at",
    }
    # Y nada del ruido llegó a los valores.
    serializado = json.dumps(
        {"cond": clima.condition, "lugar": clima.place.label}, ensure_ascii=False
    )
    for basura in ("cod", "icon", "stations", "3688689"):
        assert basura not in serializado


def test_un_doble_puede_sustituir_al_proveedor(loop_de_test: BlockingPortal) -> None:
    """El ``Protocol`` se cumple por estructura, sin heredar de nada."""

    class Doble:
        @property
        def name(self) -> str:
            return "doble"

        async def current(
            self, location: str, *, country_code: str | None = None
        ) -> CurrentWeather:
            raise WeatherNotFound("nada")

    doble: WeatherProvider = Doble()
    set_weather_provider(doble)

    assert get_weather_provider() is doble
    with pytest.raises(WeatherNotFound):
        _consultar(loop_de_test, doble)


def test_el_proveedor_real_cumple_la_interfaz() -> None:
    """Verificación estructural: si dejara de cumplirla, mypy fallaría aquí."""
    proveedor, _ = _proveedor(_camino_feliz())
    conforme: WeatherProvider = proveedor

    assert conforme.name == PROVIDER_NAME


# --- Traducción de errores ---------------------------------------------------


def test_un_lugar_que_no_existe_es_NotFound(loop_de_test: BlockingPortal) -> None:
    """Una lista vacía es un 200 perfectamente válido, no un fallo del servicio."""
    proveedor, grabadora = _proveedor(_camino_feliz(geo=[]))

    with pytest.raises(WeatherNotFound):
        _consultar(loop_de_test, proveedor, "Xyzzyland")

    # Y no se llegó a pedir el clima: sin coordenadas no hay qué preguntar.
    assert grabadora.rutas() == ["/geo/1.0/direct"]


def test_un_nombre_vacio_no_llega_ni_a_salir(loop_de_test: BlockingPortal) -> None:
    proveedor, grabadora = _proveedor(_camino_feliz())

    with pytest.raises(WeatherNotFound):
        _consultar(loop_de_test, proveedor, "   ")

    assert grabadora.peticiones == []


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
def test_los_errores_http_se_traducen_a_Unavailable(
    loop_de_test: BlockingPortal, status: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"cod": status, "message": "Invalid API key"})

    proveedor, _ = _proveedor(handler)

    with pytest.raises(WeatherUnavailable) as exc:
        _consultar(loop_de_test, proveedor)

    assert exc.value.provider_status == status
    # El mensaje que sale es SEGURO: nada del proveedor.
    assert "Invalid API key" not in str(exc.value)
    assert API_KEY not in str(exc.value)


def test_el_401_avisa_de_la_key_recien_creada_en_el_log(
    loop_de_test: BlockingPortal, caplog: pytest.LogCaptureFixture
) -> None:
    """El diagnóstico que ahorra media hora: una key nueva tarda en activarse."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"cod": 401, "message": "Invalid API key"})

    proveedor, _ = _proveedor(handler)

    with caplog.at_level(logging.ERROR, logger="app.services.weather.openweathermap"):
        with pytest.raises(WeatherUnavailable):
            _consultar(loop_de_test, proveedor)

    mensaje = "\n".join(r.getMessage() for r in caplog.records)
    assert "activarse" in mensaje
    assert "ROVER_WEATHER_API_KEY" in mensaje
    # La causa real SÍ va al log del servidor…
    assert "Invalid API key" in mensaje
    # …pero la key jamás.
    assert API_KEY not in mensaje


def test_la_red_caida_se_traduce_a_Unavailable(loop_de_test: BlockingPortal) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin ruta al host")

    proveedor, _ = _proveedor(handler)

    with pytest.raises(WeatherUnavailable):
        _consultar(loop_de_test, proveedor)


def test_un_cuerpo_ilegible_no_escapa_como_error_de_json(
    loop_de_test: BlockingPortal,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>error</html>")

    proveedor, _ = _proveedor(handler)

    with pytest.raises(WeatherUnavailable):
        _consultar(loop_de_test, proveedor)


def test_un_200_sin_temperatura_es_un_fallo_y_no_un_cero(
    loop_de_test: BlockingPortal,
) -> None:
    """Inventar 0 °C sería peor que fallar: el modelo lo contaría como cierto."""
    incoherente = {k: v for k, v in CLIMA_BOGOTA.items() if k != "main"}
    proveedor, _ = _proveedor(_camino_feliz(clima=incoherente))

    with pytest.raises(WeatherUnavailable):
        _consultar(loop_de_test, proveedor)


def test_un_geocoding_sin_coordenadas_es_NotFound(loop_de_test: BlockingPortal) -> None:
    proveedor, _ = _proveedor(_camino_feliz(geo=[{"name": "Nada", "country": "CO"}]))

    with pytest.raises(WeatherNotFound):
        _consultar(loop_de_test, proveedor)


def test_todos_los_errores_comparten_la_raiz_de_dominio() -> None:
    """Quien no quiera distinguirlos captura uno solo (mismo criterio que LLMError)."""
    assert issubclass(WeatherNotFound, WeatherError)
    assert issubclass(WeatherUnavailable, WeatherError)
    assert issubclass(WeatherNotConfigured, WeatherError)


# --- El registro (el punto de cambio de proveedor) ---------------------------


def test_sin_key_no_hay_proveedor_ni_se_considera_configurado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "weather_api_key", None)
    reset_weather_provider()

    assert is_weather_configured() is False
    with pytest.raises(WeatherNotConfigured):
        get_weather_provider()


def test_un_proveedor_inyectado_cuenta_como_configurado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lo que permite probar el ciclo completo sin key y sin red."""
    monkeypatch.setattr(settings, "weather_api_key", None)

    class Doble:
        @property
        def name(self) -> str:
            return "doble"

        async def current(
            self, location: str, *, country_code: str | None = None
        ) -> CurrentWeather:  # pragma: no cover
            raise WeatherNotFound("nada")

    set_weather_provider(Doble())

    assert is_weather_configured() is True


def test_con_key_se_construye_el_de_OpenWeatherMap(monkeypatch: pytest.MonkeyPatch) -> None:
    """El registro es el ÚNICO que conoce la implementación concreta.

    Este test es la contraparte del punto de cambio: cuando se enchufe
    Open-Meteo, es la única aserción del repo que habría que actualizar.
    """
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "weather_api_key", SecretStr("una-key"))
    reset_weather_provider()

    proveedor = get_weather_provider()

    assert isinstance(proveedor, OpenWeatherMapProvider)
    assert proveedor.name == PROVIDER_NAME
    # Y se cachea: no se reconstruye en cada consulta.
    assert get_weather_provider() is proveedor
