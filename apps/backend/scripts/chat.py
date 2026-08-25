"""Chatear con Rover desde la terminal, sin sacar el token a mano (SOLO DEV).

**No es parte del producto ni corre en CI.** Es tooling: automatiza el
`login → access_token → POST /v1/chat` que el README documenta como dos `curl`
encadenados, para poder probar el agente escribiendo una frase.

    cd apps/backend
    uv run python -m scripts.chat "¿qué tal el clima en Bogotá?"
    uv run python -m scripts.chat "¿y me llevo chaqueta?" <conversation_id>

Necesita en ``apps/backend/.env`` (ver ``.env.example``):

    ROVER_DEV_TEST_EMAIL=tu-usuario-de-pruebas@example.com
    ROVER_DEV_TEST_PASSWORD=la-contrasena-de-ese-usuario

Si faltan, el script lo dice y no manda nada.


## Por qué Python y no un `chat.sh` con curl

La tarea pedía decidir. Un script de bash sería el `curl` del README con menos
teclas, y aun así sale perdiendo en cuatro puntos concretos:

1. **Leer el `.env`.** `source .env` **ejecuta** el archivo: un valor con
   espacios, con un `#` dentro o una comilla desbalanceada rompe la carga o
   —peor— corre algo. Aquí lo lee `pydantic-settings`, que es el mismo parser
   que usa la app, con las mismas reglas.
2. **Parsear el SSE.** Cada marco es un JSON con `type` (`start`/`delta`/
   `status`/`done`/`error`). En bash eso es `jq` por marco —una dependencia
   más que instalar— y aún así queda torpe imprimir los `delta` sin salto de
   línea entre ellos.
3. **Los errores.** El backend responde el cuerpo de la HU-1.8 con un `code`
   accionable (`invalid_credentials`, `email_not_confirmed`, `rate_limited`…).
   Traducir cada uno a una pista útil es un `match` de diez líneas; en bash es
   `jq` otra vez y comparación de cadenas.
4. **Ya hay convención.** `scripts/check_llm.py` y `scripts/check_tools.py`
   viven aquí y se invocan igual (`uv run python -m scripts.…`). Un `.sh`
   suelto sería un tercer patrón para el mismo tipo de herramienta.

El costo de Python aquí es **cero**: `httpx` y `pydantic-settings` ya son
dependencias del backend, así que no se instala nada.


## Por qué la config vive AQUÍ y no en `app/core/config.py`

Las credenciales de prueba son de la **herramienta**, no de la aplicación:
meterlas en `Settings` metería un usuario de pruebas en la superficie de
configuración de producción, donde no pinta nada. Este módulo declara su propio
`BaseSettings` apuntando al **mismo `.env`** y con el **mismo prefijo**
`ROVER_`, así que se configura como todo lo demás sin ensuciar la app. (Y al
revés tampoco molesta: `Settings` usa `extra="ignore"`, así que estas variables
en el `.env` no afectan al arranque del backend.)


## Este script NO importa `app`

Habla con la API por HTTP, como cualquier cliente. Es lo que hace que sirva
contra un backend que corre en Docker, en otra máquina o en un entorno remoto
(`ROVER_DEV_BASE_URL`) y no solo contra el código de este checkout.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

#: El .env del backend (apps/backend/.env), anclado a este archivo para que la
#: carga no dependa del directorio desde el que se lance el script.
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

#: Timeouts pensados para una conversación, no para una API normal: el modelo
#: puede tardar en arrancar y una respuesta larga tarda en salir entera. El de
#: conexión sí es corto — "el backend no está levantado" debe verse rápido.
_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0)

#: Pistas por ``code`` del contrato de errores (HU-1.8). La gracia del script no
#: es reenviar el mensaje del servidor —que ya es bueno— sino decir qué hacer
#: con él **en un entorno de desarrollo**, que es donde la causa suele ser el
#: `.env` o un backend sin levantar.
_PISTAS: dict[str, str] = {
    "invalid_credentials": (
        "Revisa ROVER_DEV_TEST_EMAIL y ROVER_DEV_TEST_PASSWORD en apps/backend/.env. "
        "El backend responde lo mismo si el email no existe o si la contraseña está "
        "mal, así que comprueba los dos."
    ),
    "email_not_confirmed": (
        "El usuario existe y la contraseña es correcta, pero falta confirmar el correo. "
        "Confírmalo desde el enlace que mandó Supabase, o márcalo como confirmado en el "
        "panel de Supabase (Authentication → Users)."
    ),
    "rate_limited": (
        "Demasiados intentos seguidos. Espera un momento y vuelve a probar; el login "
        "tiene un límite estricto a propósito (10/min por IP, HU-1.7)."
    ),
    "service_unavailable": (
        "El backend está arriba pero su proveedor no responde (Supabase en el login, "
        "el LLM en el chat). Mira los logs del servidor: la causa real queda ahí."
    ),
    "validation_error": (
        "El cuerpo no cumple el contrato. Si es el login, revisa que el email del .env "
        "tenga forma de email; si es el chat, que el mensaje no esté vacío ni pase de "
        "8000 caracteres."
    ),
    "not_found": (
        "Ese conversation_id no existe, está borrado o es de otro usuario — los tres "
        "casos responden igual a propósito. Empieza una conversación nueva (sin pasar "
        "el segundo argumento)."
    ),
}


class DevSettings(BaseSettings):
    """Config de ESTA herramienta. Ver el docstring del módulo para por qué aquí."""

    model_config = SettingsConfigDict(
        env_prefix="ROVER_",
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Credenciales del usuario de PRUEBAS. Sin default: si faltan, el script
    #: para con una explicación en vez de mandar un login vacío.
    dev_test_email: str | None = None
    #: ``SecretStr`` aunque sea de desarrollo: es la misma disciplina del resto
    #: de la config, y evita que la contraseña salga en un traceback si algo
    #: revienta a mitad.
    dev_test_password: SecretStr | None = None

    #: Contra qué backend se habla. Configurable por si algún día apunta a un
    #: despliegue de staging en vez de al uvicorn de al lado.
    dev_base_url: str = "http://localhost:8000"


# --- Salida ------------------------------------------------------------------
# La RESPUESTA del modelo va a stdout y todo lo demás (login, estado, ids) a
# stderr. Así `… > respuesta.txt` guarda solo lo que dijo Rover, y el
# conversation_id sigue viéndose en la terminal para copiarlo.

_COLOR = sys.stderr.isatty()


def _meta(texto: str) -> None:
    """Una línea de contexto, atenuada, por stderr."""
    print(f"\033[2m{texto}\033[0m" if _COLOR else texto, file=sys.stderr, flush=True)


def _error(titulo: str, detalle: str = "") -> int:
    """Un fallo, en rojo si la terminal lo admite. Devuelve el código de salida."""
    marca = f"\033[31m✗ {titulo}\033[0m" if _COLOR else f"✗ {titulo}"
    print(marca, file=sys.stderr)
    if detalle:
        print(f"  {detalle}", file=sys.stderr)
    return 1


def _faltan_credenciales() -> int:
    return _error(
        "Faltan las credenciales del usuario de pruebas.",
        "Añade esto a apps/backend/.env (es SOLO para desarrollo local; no uses una\n"
        "  cuenta real de producción):\n\n"
        "    ROVER_DEV_TEST_EMAIL=tu-usuario-de-pruebas@example.com\n"
        "    ROVER_DEV_TEST_PASSWORD=la-contrasena-de-ese-usuario\n\n"
        "  Si no tienes usuario de pruebas, créalo y confírmalo:\n"
        "    curl -s localhost:8000/v1/auth/register -H 'Content-Type: application/json' \\\n"
        '      -d \'{"email":"dev@example.com","password":"una-contrasena-larga"}\'',
    )


def _detalle_del_error(cuerpo: bytes, status: int) -> tuple[str, str]:
    """Cuerpo de error de la API → ``(mensaje, pista)``.

    Tolerante con lo que no tenga la forma esperada: un proxy delante puede
    devolver HTML, y un script de desarrollo que reviente parseando la página de
    error de nginx sería peor que uno que enseñe el status.
    """
    try:
        datos: Any = json.loads(cuerpo)
        error = datos["error"]
        codigo = str(error.get("code", ""))
        mensaje = str(error.get("message", ""))
    except (ValueError, KeyError, TypeError, AttributeError):
        return f"HTTP {status}: {cuerpo[:200].decode('utf-8', 'replace')}", ""
    return f"HTTP {status} ({codigo}): {mensaje}", _PISTAS.get(codigo, "")


# --- Los dos pasos -----------------------------------------------------------


def login(client: httpx.Client, *, email: str, password: str) -> str | None:
    """Devuelve el ``access_token``, o ``None`` tras explicar qué pasó."""
    _meta(f"→ login como {email} en {client.base_url}")
    try:
        respuesta = client.post("/v1/auth/login", json={"email": email, "password": password})
    except httpx.ConnectError:
        _error(
            f"No hay nadie escuchando en {client.base_url}.",
            "Levanta el backend (uv run uvicorn app.main:app --reload) o apunta a otro\n"
            "  entorno con ROVER_DEV_BASE_URL.",
        )
        return None
    except httpx.HTTPError as exc:
        _error(f"No se pudo hablar con {client.base_url}.", f"{type(exc).__name__}: {exc}")
        return None

    if respuesta.status_code != 200:
        mensaje, pista = _detalle_del_error(respuesta.content, respuesta.status_code)
        _error(f"El login falló. {mensaje}", pista)
        return None

    # Un 200 con la sesión en otro sitio sería un cambio del contrato: se avisa
    # en vez de seguir con un token vacío, que acabaría en un 401 del chat y
    # mandaría a depurar el sitio equivocado.
    try:
        token = respuesta.json()["session"]["access_token"]
    except (ValueError, KeyError, TypeError):
        _error(
            "El login respondió 200 pero sin session.access_token.",
            f"Cuerpo recibido: {respuesta.text[:200]}",
        )
        return None

    if not isinstance(token, str) or not token:
        _error("El login devolvió un access_token vacío.")
        return None

    _meta("  token obtenido")
    return token


def chat(client: httpx.Client, *, token: str, mensaje: str, conversation_id: str | None) -> int:
    """Manda el mensaje y va imprimiendo la respuesta. Devuelve el código de salida."""
    cuerpo: dict[str, Any] = {"message": mensaje}
    if conversation_id:
        cuerpo["conversation_id"] = conversation_id
        _meta(f"→ continuando la conversación {conversation_id}")
    else:
        _meta("→ conversación nueva")

    id_de_la_conversacion = conversation_id
    hubo_texto = False
    salida = 0

    try:
        with client.stream(
            "POST",
            "/v1/chat",
            json=cuerpo,
            headers={"Authorization": f"Bearer {token}"},
        ) as respuesta:
            if respuesta.status_code != 200:
                # El fallo ANTES del stream llega como status HTTP normal
                # (HU-2.4). Hay que leer el cuerpo a mano: se abrió en streaming.
                respuesta.read()
                mensaje_error, pista = _detalle_del_error(respuesta.content, respuesta.status_code)
                return _error(f"El chat falló antes de empezar. {mensaje_error}", pista)

            for linea in respuesta.iter_lines():
                if not linea.startswith("data:"):
                    # Líneas en blanco entre marcos, y comentarios de keep-alive.
                    continue
                try:
                    evento = json.loads(linea[len("data:") :].strip())
                except ValueError:
                    # Misma política que el backend y que @rover/shared: un
                    # marco roto no tira una respuesta que ya está en pantalla.
                    continue

                match evento.get("type"):
                    case "start":
                        id_de_la_conversacion = evento.get("conversation_id")
                        nueva = " (nueva)" if evento.get("created") else ""
                        _meta(f"  conversación {id_de_la_conversacion}{nueva}\n")
                    case "delta":
                        # A stdout y sin salto: los trozos se concatenan hasta
                        # formar la respuesta.
                        print(evento.get("text", ""), end="", flush=True)
                        hubo_texto = True
                    case "status":
                        # La fase de herramienta (HU-2.6): lo único que el
                        # backend cuenta de ella es el nombre y una frase.
                        _meta(f"  [{evento.get('tool')}] {evento.get('message')}")
                    case "error":
                        # Fallo A MITAD: el 200 ya salió, así que el error viene
                        # dentro del stream. No se corta aquí: se sale del bucle
                        # para imprimir igual el conversation_id — el turno se
                        # perdió, pero la conversación existe (la pregunta SÍ se
                        # guardó, HU-2.4) y se puede seguir en ella.
                        if hubo_texto:
                            print(file=sys.stdout, flush=True)
                            hubo_texto = False
                        error = evento.get("error") or {}
                        codigo = str(error.get("code", ""))
                        salida = _error(
                            f"El stream se cortó ({codigo}): {error.get('message', '')}",
                            _PISTAS.get(codigo, ""),
                        )
                        break
                    case "done":
                        pass
    except httpx.ReadTimeout:
        print(file=sys.stdout, flush=True)
        return _error(
            "El backend dejó de mandar trozos y se agotó la espera.",
            "Mira los logs del servidor: la línea app.llm dice cómo terminó la llamada.",
        )
    except httpx.HTTPError as exc:
        print(file=sys.stdout, flush=True)
        return _error("Se cortó la conexión con el backend.", f"{type(exc).__name__}: {exc}")

    if hubo_texto:
        print(file=sys.stdout, flush=True)

    if id_de_la_conversacion:
        # Lo más útil que puede imprimir este script: el comando exacto para
        # seguir hablando, listo para copiar.
        _meta("")
        _meta(f"conversation_id: {id_de_la_conversacion}")
        _meta(f'para continuar:  uv run python -m scripts.chat "…" {id_de_la_conversacion}')
    return salida


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="uv run python -m scripts.chat",
        description="Chatea con Rover en local: hace el login y manda el mensaje. Solo desarrollo.",
        epilog=(
            "Credenciales: ROVER_DEV_TEST_EMAIL y ROVER_DEV_TEST_PASSWORD en "
            "apps/backend/.env. Backend: ROVER_DEV_BASE_URL (default "
            "http://localhost:8000). Si el mensaje empieza por '-', ponlo tras un '--'."
        ),
    )
    parser.add_argument("mensaje", help="Lo que le dices a Rover.")
    parser.add_argument(
        "conversation_id",
        nargs="?",
        default=None,
        help="Conversación a continuar. Si se omite, se crea una nueva.",
    )
    args = parser.parse_args()

    settings = DevSettings()
    if settings.dev_test_email is None or settings.dev_test_password is None:
        return _faltan_credenciales()

    with httpx.Client(base_url=settings.dev_base_url.rstrip("/"), timeout=_TIMEOUT) as client:
        token = login(
            client,
            email=settings.dev_test_email,
            password=settings.dev_test_password.get_secret_value(),
        )
        if token is None:
            return 1
        return chat(
            client,
            token=token,
            mensaje=args.mensaje,
            conversation_id=args.conversation_id,
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        # Cortar con Ctrl-C es un uso NORMAL de esto (una respuesta larga que ya
        # se leyó): se sale limpio en vez de escupir un traceback. El backend lo
        # registra como `llm_outcome=cancelled` y no persiste la respuesta.
        print(file=sys.stdout, flush=True)
        _meta("cancelado")
        raise SystemExit(130) from None
