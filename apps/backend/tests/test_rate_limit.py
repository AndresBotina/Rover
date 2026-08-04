"""Tests del rate limiting propio de la API (HU-1.7).

Tres niveles, porque son tres cosas distintas:

- el **almacén** (ventana deslizante, reseteo, claves independientes,
  atomicidad) se prueba directo, con un reloj inyectado para no dormir;
- la **obtención de la IP** tras el proxy se prueba sobre peticiones armadas a
  mano, incluida la falsificación que debe ignorarse;
- el **límite aplicado** se prueba por HTTP contra la app real: el 429 en el
  formato único, las cabeceras, el límite estricto de auth y la cuota por
  usuario con su multiplicador de plan.

Nada aquí toca Supabase ni una base real: el middleware corta ANTES de resolver
la ruta, así que la mayoría de los casos se ejercen contra rutas que responden
401 o 422 sin salir del proceso.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from starlette.requests import Request

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.rate_limit import (
    UNKNOWN_CLIENT,
    InMemoryRateLimitStore,
    RateLimitScope,
    client_ip,
    make_key,
    reset_rate_limit_store,
    rule_for_user,
)
from app.main import app
from app.models import Plan, UserProfile
from tests import auth_utils
from tests.conftest import BaseDeTest

# IP "real" que el proxy de confianza pondría al final de X-Forwarded-For.
_IP = "203.0.113.7"
_OTRA_IP = "198.51.100.4"


def _ejecutar(corutina: Coroutine[Any, Any, Any]) -> Any:
    """Corre una corutina del almacén en memoria en su propio loop.

    Aquí ``asyncio.run`` es seguro y se queda: el almacén no toca la base ni
    ninguna otra cosa que sobreviva al loop (lo que sí pasaba con el engine de
    SQLite, ver la fixture ``bd`` de conftest).
    """
    return asyncio.run(corutina)


def _desde(ip: str) -> dict[str, str]:
    """Cabeceras que hacen que la petición se contabilice como venida de ``ip``."""
    return {"X-Forwarded-For": ip}


class _Reloj:
    """Reloj controlado: probar el paso de la ventana sin dormir ni depender del CI."""

    def __init__(self, inicio: float = 1_000.0) -> None:
        self.ahora = inicio

    def __call__(self) -> float:
        return self.ahora

    def avanzar(self, segundos: float) -> None:
        self.ahora += segundos


# --- Almacén: ventana deslizante ---------------------------------------------


def test_el_almacen_permite_justo_hasta_el_limite() -> None:
    almacen = InMemoryRateLimitStore(now=_Reloj())

    async def escenario() -> list[Any]:
        return [await almacen.hit("k", limit=3, window_seconds=60) for _ in range(4)]

    permitidas, remanentes = [], []
    for resultado in _ejecutar(escenario()):
        permitidas.append(resultado.allowed)
        remanentes.append(resultado.remaining)

    assert permitidas == [True, True, True, False]
    # El cupo restante se anuncia bien, y al rechazar es 0.
    assert remanentes == [2, 1, 0, 0]


def test_el_contador_se_resetea_al_pasar_la_ventana() -> None:
    reloj = _Reloj()
    almacen = InMemoryRateLimitStore(now=reloj)

    async def escenario() -> tuple[Any, Any, Any]:
        await almacen.hit("k", limit=2, window_seconds=60)
        await almacen.hit("k", limit=2, window_seconds=60)
        agotado = await almacen.hit("k", limit=2, window_seconds=60)

        # A falta de un segundo para que la marca más vieja salga: sigue lleno.
        reloj.avanzar(59)
        casi = await almacen.hit("k", limit=2, window_seconds=60)

        # Superada la ventana, el cupo vuelve entero.
        reloj.avanzar(2)
        libre = await almacen.hit("k", limit=2, window_seconds=60)
        return agotado, casi, libre

    agotado, casi, libre = _ejecutar(escenario())

    assert agotado.allowed is False
    # Retry-After es EXACTO: lo que falta para que salga la marca más antigua.
    assert agotado.retry_after_seconds == 60
    assert casi.allowed is False and casi.retry_after_seconds == 1
    assert libre.allowed is True


def test_la_ventana_es_deslizante_no_fija() -> None:
    """El punto del algoritmo: no hay ráfaga del doble del límite en el borde."""
    reloj = _Reloj()
    almacen = InMemoryRateLimitStore(now=reloj)

    async def escenario() -> Any:
        # Dos peticiones al final de un "minuto".
        await almacen.hit("k", limit=2, window_seconds=60)
        await almacen.hit("k", limit=2, window_seconds=60)
        # Con ventana FIJA, cruzar el corte del minuto daría cupo nuevo.
        reloj.avanzar(1)
        return await almacen.hit("k", limit=2, window_seconds=60)

    assert _ejecutar(escenario()).allowed is False


def test_claves_distintas_cuentan_por_separado() -> None:
    almacen = InMemoryRateLimitStore(now=_Reloj())

    async def escenario() -> tuple[Any, Any]:
        await almacen.hit("uno", limit=1, window_seconds=60)
        return (
            await almacen.hit("uno", limit=1, window_seconds=60),
            await almacen.hit("dos", limit=1, window_seconds=60),
        )

    repetida, otra = _ejecutar(escenario())

    assert repetida.allowed is False
    assert otra.allowed is True


def test_peek_consulta_sin_consumir() -> None:
    almacen = InMemoryRateLimitStore(now=_Reloj())

    async def escenario() -> tuple[Any, Any]:
        await almacen.hit("k", limit=2, window_seconds=60)
        antes = await almacen.peek("k", limit=2, window_seconds=60)
        await almacen.peek("k", limit=2, window_seconds=60)
        despues = await almacen.peek("k", limit=2, window_seconds=60)
        return antes, despues

    antes, despues = _ejecutar(escenario())

    assert antes.remaining == 1
    assert despues.remaining == 1, "peek no debe gastar cupo"


def test_una_peticion_rechazada_no_alarga_el_castigo() -> None:
    """Insistir estando bloqueado no debe reiniciar la cuenta atrás."""
    reloj = _Reloj()
    almacen = InMemoryRateLimitStore(now=reloj)

    async def escenario() -> Any:
        await almacen.hit("k", limit=1, window_seconds=60)
        reloj.avanzar(30)
        await almacen.hit("k", limit=1, window_seconds=60)  # rechazada
        reloj.avanzar(31)  # la marca original ya salió de la ventana
        return await almacen.hit("k", limit=1, window_seconds=60)

    assert _ejecutar(escenario()).allowed is True


def test_rafagas_concurrentes_sobre_el_almacen_no_superan_el_limite() -> None:
    almacen = InMemoryRateLimitStore(now=_Reloj())

    async def escenario() -> list[Any]:
        return list(
            await asyncio.gather(*(almacen.hit("k", limit=5, window_seconds=60) for _ in range(50)))
        )

    resultados = _ejecutar(escenario())

    assert sum(1 for r in resultados if r.allowed) == 5


# --- IP del cliente detrás del proxy -----------------------------------------


def _peticion(*, xff: list[str] | None = None, peer: str | None = "10.0.0.1") -> Request:
    """Petición armada a mano, con las cabeceras y el peer TCP que se quieran."""
    cabeceras = [(b"x-forwarded-for", valor.encode()) for valor in (xff or [])]
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/users/me",
        "raw_path": b"/v1/users/me",
        "query_string": b"",
        "root_path": "",
        "headers": cabeceras,
        "server": ("testserver", 80),
        "client": (peer, 4444) if peer is not None else None,
    }
    return Request(scope)


def test_la_ip_es_la_que_puso_el_proxy_de_confianza_no_la_del_cliente() -> None:
    """Lo declarado por el cliente va a la IZQUIERDA y se ignora."""
    peticion = _peticion(xff=[f"1.2.3.4, {_IP}"])

    assert client_ip(peticion, trusted_proxies=1) == _IP


def test_no_se_puede_esquivar_el_limite_falsificando_x_forwarded_for() -> None:
    """Cambiar el valor inventado en cada petición no cambia la clave."""
    ips = {
        client_ip(_peticion(xff=[f"{inventada}, {_IP}"]), trusted_proxies=1)
        for inventada in ("1.1.1.1", "8.8.8.8", "no-es-una-ip", "9.9.9.9, 7.7.7.7")
    }

    assert ips == {_IP}


def test_con_dos_proxies_de_confianza_se_cuenta_un_salto_mas() -> None:
    """Un CDN delante de Render: el cliente real está una posición más adentro."""
    peticion = _peticion(xff=[f"1.2.3.4, {_IP}, 192.0.2.9"])

    assert client_ip(peticion, trusted_proxies=2) == _IP


def test_sin_proxies_de_confianza_la_cabecera_se_ignora() -> None:
    """Sin nadie fiable delante, X-Forwarded-For lo escribe el cliente."""
    peticion = _peticion(xff=["1.2.3.4"], peer="10.0.0.1")

    assert client_ip(peticion, trusted_proxies=0) == "10.0.0.1"


def test_sin_cabecera_se_cae_al_peer_tcp() -> None:
    assert client_ip(_peticion(peer="10.0.0.1"), trusted_proxies=1) == "10.0.0.1"


def test_la_cabecera_repetida_se_trata_como_una_sola_lista() -> None:
    """Algunos proxies mandan varias X-Forwarded-For en vez de una con comas."""
    peticion = _peticion(xff=["1.2.3.4", _IP])

    assert client_ip(peticion, trusted_proxies=1) == _IP


def test_se_descartan_las_entradas_que_no_son_ip() -> None:
    """Basura en la cabecera no puede crear claves nuevas en el almacén."""
    peticion = _peticion(xff=[f"basura, , {_IP}"])

    assert client_ip(peticion, trusted_proxies=1) == _IP


def test_se_acepta_el_puerto_y_se_normaliza_ipv6() -> None:
    con_puerto = _peticion(xff=[f"{_IP}:5678"])
    ipv6 = _peticion(xff=["[2001:0db8:0000::1]:5678"])

    assert client_ip(con_puerto, trusted_proxies=1) == _IP
    assert client_ip(ipv6, trusted_proxies=1) == "2001:db8::1"


def test_sin_ip_utilizable_se_usa_un_cubo_de_reserva() -> None:
    peticion = _peticion(xff=["basura"], peer=None)

    assert client_ip(peticion, trusted_proxies=1) == UNKNOWN_CLIENT


# --- El límite aplicado por HTTP ---------------------------------------------


@pytest.fixture
def limites_pequenos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Límites diminutos para poder agotarlos en pocas peticiones."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_default_limit", 3)
    monkeypatch.setattr(settings, "rate_limit_default_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_auth_limit", 2)
    monkeypatch.setattr(settings, "rate_limit_auth_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_trusted_proxies", 1)


def test_superar_el_limite_global_responde_429_en_el_formato_unico(
    limites_pequenos: None,
) -> None:
    with TestClient(app) as client:
        respuestas = [client.get("/v1/users/me", headers=_desde(_IP)) for _ in range(4)]

    # Las tres primeras llegan al endpoint (401: no hay token). La cuarta, no.
    assert [r.status_code for r in respuestas] == [401, 401, 401, 429]

    bloqueada = respuestas[-1]
    cuerpo = bloqueada.json()
    assert set(cuerpo) == {"error"}
    assert cuerpo["error"] == {
        "code": ErrorCode.RATE_LIMITED.value,
        "message": "Demasiadas peticiones; espera un momento antes de reintentar.",
        "details": None,
        "error_id": None,
    }


def test_el_429_trae_retry_after_y_las_cabeceras_de_cupo(limites_pequenos: None) -> None:
    with TestClient(app) as client:
        for _ in range(3):
            client.get("/v1/users/me", headers=_desde(_IP))
        bloqueada = client.get("/v1/users/me", headers=_desde(_IP))

    assert bloqueada.status_code == 429
    # Segundos, nunca 0: un Retry-After de 0 invita a reintentar de inmediato.
    assert 1 <= int(bloqueada.headers["Retry-After"]) <= 60
    assert bloqueada.headers["X-RateLimit-Limit"] == "3"
    assert bloqueada.headers["X-RateLimit-Remaining"] == "0"
    assert bloqueada.headers["X-RateLimit-Reset"] == bloqueada.headers["Retry-After"]


def test_dos_ips_distintas_tienen_contadores_independientes(limites_pequenos: None) -> None:
    with TestClient(app) as client:
        for _ in range(4):
            client.get("/v1/users/me", headers=_desde(_IP))
        otra = client.get("/v1/users/me", headers=_desde(_OTRA_IP))

    assert otra.status_code == 401, "la IP agotada no puede gastar el cupo de otra"


def test_los_endpoints_de_auth_tienen_un_limite_mas_estricto(limites_pequenos: None) -> None:
    """Con el global en 3 y el de auth en 2, login se corta antes."""
    with TestClient(app) as client:
        logins = [client.post("/v1/auth/login", json={}, headers=_desde(_IP)) for _ in range(3)]
        # El ámbito global sigue intacto: son contadores separados.
        global_ = client.get("/v1/users/me", headers=_desde(_IP))

    # 422 (cuerpo vacío) mientras hay cupo; el middleware corta antes de validar.
    assert [r.status_code for r in logins] == [422, 422, 429]
    assert global_.status_code == 401


def test_register_comparte_el_cupo_estricto_con_login(limites_pequenos: None) -> None:
    """Un mismo cubo para los dos: quien crea cuentas en masa alterna endpoints."""
    with TestClient(app) as client:
        client.post("/v1/auth/login", json={}, headers=_desde(_IP))
        client.post("/v1/auth/register", json={}, headers=_desde(_IP))
        tercera = client.post("/v1/auth/register", json={}, headers=_desde(_IP))

    assert tercera.status_code == 429


def test_los_defaults_dejan_auth_mas_estricto_que_el_global() -> None:
    """Los valores que se despliegan, no solo los del test."""
    por_ventana = settings.rate_limit_auth_limit / settings.rate_limit_auth_window_seconds
    global_por_ventana = (
        settings.rate_limit_default_limit / settings.rate_limit_default_window_seconds
    )

    assert por_ventana < global_por_ventana


def test_las_rutas_inexistentes_tambien_consumen_cupo(limites_pequenos: None) -> None:
    """Por esto el límite es middleware y no dependencia del router: un escáner
    dispara a rutas que no existen y debe gastar cupo igual."""
    with TestClient(app) as client:
        respuestas = [client.get("/v1/no-existe", headers=_desde(_IP)) for _ in range(4)]

    assert [r.status_code for r in respuestas] == [404, 404, 404, 429]


def test_el_healthcheck_esta_exento(limites_pequenos: None) -> None:
    """Render sondea /v1/health sin parar; limitarlo tumbaría deploys sanos."""
    with TestClient(app) as client:
        respuestas = [client.get("/v1/health", headers=_desde(_IP)) for _ in range(10)]

    assert {r.status_code for r in respuestas} == {200}


def test_el_interruptor_apaga_el_rate_limiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_default_limit", 1)

    with TestClient(app) as client:
        respuestas = [client.get("/v1/users/me", headers=_desde(_IP)) for _ in range(5)]

    assert {r.status_code for r in respuestas} == {401}


def test_el_rechazo_se_registra_como_warning_sin_datos_sensibles(
    limites_pequenos: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.api.middleware"):
        with TestClient(app) as client:
            for _ in range(4):
                client.get(
                    "/v1/users/me",
                    headers={**_desde(_IP), "Authorization": "Bearer un-token-secreto"},
                )

    registros = [r.getMessage() for r in caplog.records if r.name == "app.api.middleware"]
    assert len(registros) == 1, "un rechazo, una línea (no una por petición del cliente)"
    assert _IP in registros[0] and "/v1/users/me" in registros[0]
    # El token viajaba en la petición y NO puede acabar en el log.
    assert "un-token-secreto" not in caplog.text


def test_rafagas_concurrentes_por_http_no_superan_el_limite(limites_pequenos: None) -> None:
    """El invariante de cara al usuario: veinte peticiones a la vez, tres pasan."""

    async def escenario() -> list[int]:
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://test") as client:
            respuestas = await asyncio.gather(
                *(client.get("/v1/users/me", headers=_desde(_IP)) for _ in range(20))
            )
        return [r.status_code for r in respuestas]

    codigos = _ejecutar(escenario())

    assert codigos.count(429) == 17
    assert codigos.count(401) == 3


# --- Cuota por usuario y enganche de los planes ------------------------------


@pytest.fixture(autouse=True)
def _entorno_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """JWKS de prueba (la base la entrega la fixture ``bd`` de conftest)."""
    auth_utils.install_auth_env(monkeypatch)


def _poner_plan(bd: BaseDeTest, user_id: uuid.UUID, plan: Plan) -> None:
    async def actualizar() -> None:
        async with bd.factory() as session:
            await session.execute(
                update(UserProfile).where(UserProfile.id == user_id).values(plan=plan)
            )
            await session.commit()

    bd.run(actualizar)


@pytest.fixture
def cuota_de_usuario(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cuota de usuario diminuta, con el límite por IP fuera de juego."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_default_limit", 1_000)
    monkeypatch.setattr(settings, "rate_limit_user_limit", 2)
    monkeypatch.setattr(settings, "rate_limit_user_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_pro_multiplier", 1.0)


def test_la_cuota_por_usuario_corta_con_429(
    bd: BaseDeTest, cuota_de_usuario: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = auth_utils.make_token(sub=str(uuid.uuid4()))

    with TestClient(app) as client:
        cabeceras = {"Authorization": f"Bearer {token}", **_desde(_IP)}
        respuestas = [client.get("/v1/users/me", headers=cabeceras) for _ in range(3)]

    assert [r.status_code for r in respuestas] == [200, 200, 429]
    assert respuestas[-1].json()["error"]["code"] == ErrorCode.RATE_LIMITED.value
    assert int(respuestas[-1].headers["Retry-After"]) >= 1


def test_dos_usuarios_desde_la_misma_ip_no_se_gastan_el_cupo(
    bd: BaseDeTest, cuota_de_usuario: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El motivo de limitar por usuario y no solo por IP: detrás de un NAT (o de
    una operadora móvil) mucha gente legítima comparte dirección."""
    primera = auth_utils.make_token(sub=str(uuid.uuid4()), email="una@example.com")
    segunda = auth_utils.make_token(sub=str(uuid.uuid4()), email="otra@example.com")

    with TestClient(app) as client:
        for _ in range(3):
            client.get(
                "/v1/users/me", headers={"Authorization": f"Bearer {primera}", **_desde(_IP)}
            )
        otra = client.get(
            "/v1/users/me", headers={"Authorization": f"Bearer {segunda}", **_desde(_IP)}
        )

    assert otra.status_code == 200


def test_el_plan_pro_recibe_mas_cupo_con_el_multiplicador(
    bd: BaseDeTest, cuota_de_usuario: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El punto de extensión de la Épica 5, ejercido de verdad: subir el
    multiplicador cambia el límite sin tocar código."""
    monkeypatch.setattr(settings, "rate_limit_pro_multiplier", 2.0)
    user_id = uuid.uuid4()
    token = auth_utils.make_token(sub=str(user_id))

    with TestClient(app) as client:
        cabeceras = {"Authorization": f"Bearer {token}", **_desde(_IP)}
        # La primera petición materializa el perfil (plan free por defecto).
        client.get("/v1/users/me", headers=cabeceras)
        _poner_plan(bd, user_id, Plan.PRO)
        reset_rate_limit_store()
        respuestas = [client.get("/v1/users/me", headers=cabeceras) for _ in range(5)]

    # 2 (límite base) × 2.0 (multiplicador pro) = 4 permitidas.
    assert [r.status_code for r in respuestas] == [200, 200, 200, 200, 429]


def test_el_multiplicador_del_plan_escala_la_regla() -> None:
    """La política, sin pasar por HTTP."""
    base = rule_for_user()
    doble = rule_for_user(multiplier=2.0)

    assert doble.limit == base.limit * 2
    assert doble.scope is RateLimitScope.USER
    assert doble.window_seconds == base.window_seconds


def test_la_cuota_de_usuario_y_la_de_ip_no_comparten_clave() -> None:
    """Un id de usuario y una IP nunca pueden caer en el mismo cubo."""
    por_ip = make_key(RateLimitScope.GLOBAL, "ip", _IP)
    por_usuario = make_key(RateLimitScope.USER, "user", _IP)

    assert por_ip != por_usuario


def test_el_429_es_identico_venga_del_middleware_o_de_la_cuota_de_usuario(
    bd: BaseDeTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dos caminos distintos, un solo contrato de error para el cliente."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_user_limit", 1)
    monkeypatch.setattr(settings, "rate_limit_default_limit", 1_000)
    token = auth_utils.make_token(sub=str(uuid.uuid4()))

    with TestClient(app) as client:
        cabeceras = {"Authorization": f"Bearer {token}", **_desde(_IP)}
        client.get("/v1/users/me", headers=cabeceras)
        por_usuario = client.get("/v1/users/me", headers=cabeceras)

        reset_rate_limit_store()
        monkeypatch.setattr(settings, "rate_limit_default_limit", 1)
        client.get("/v1/no-existe", headers=_desde(_OTRA_IP))
        por_ip = client.get("/v1/no-existe", headers=_desde(_OTRA_IP))

    assert por_usuario.status_code == por_ip.status_code == 429
    assert por_usuario.json() == por_ip.json()
    assert por_usuario.headers["X-RateLimit-Remaining"] == por_ip.headers["X-RateLimit-Remaining"]
