"""Servicio de autenticación: TODA la interacción con Supabase Auth vive aquí.

Concentra el acoplamiento al proveedor en un único módulo — el resto del
backend nunca importa nada de Supabase ni conoce la forma de sus errores;
solo ve las excepciones de dominio de más abajo. Es la mitigación al
trade-off documentado en la nota de decisión de arquitectura de la Épica 1
(docs/backlog.md): Supabase Auth es el proveedor de identidad, y ese
acoplamiento queda concentrado aquí a propósito.

Integración elegida: HTTP directo a la API de GoTrue (Supabase Auth) con
``httpx`` async, NO el SDK oficial ``supabase-py``. Motivos:
  - Esta HU solo necesita UN endpoint (``/auth/v1/signup``); el SDK trae de
    regalo postgrest, storage3 y realtime — peso y superficie que no usamos
    (y que además solo tienen cliente async desde su versión más reciente).
  - El backend es async de punta a punta: ``httpx.AsyncClient`` no bloquea el
    event loop, igual que el SDK, pero sin una capa intermedia.
  - Queremos TRADUCIR los errores de Supabase a excepciones propias (ver
    abajo); con HTTP directo controlamos nosotros el parseo del cuerpo de
    error en vez de desempacar la jerarquía de excepciones del SDK.

Usa la ANON KEY (permisos de cliente público): registrar un usuario no
requiere privilegios elevados. La SERVICE ROLE KEY queda configurada en
``app.core.config`` para operaciones administrativas futuras — esta HU NO la
usa; usarla "porque funciona" sería dar permisos de más a una operación que
no los necesita.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SIGNUP_PATH = "/auth/v1/signup"
_TOKEN_PATH = "/auth/v1/token"
_TIMEOUT_SECONDS = 10.0


class AuthError(Exception):
    """Error de autenticación ya traducido a dominio: la API nunca ve la forma de Supabase.

    El mensaje (``str(exc)``) es SEGURO para mostrar al cliente. Los detalles
    del proveedor —status HTTP, ``error_code`` y su mensaje— viajan aparte y
    son SOLO para los logs del servidor: nunca deben ir en la respuesta. Son
    el diagnóstico de GoTrue (p. ej. "email rate limit exceeded"), nunca la
    contraseña ni las llaves (Supabase no las incluye en sus errores).
    """

    def __init__(
        self,
        message: str,
        *,
        provider_status: int | None = None,
        provider_error_code: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_status = provider_status
        self.provider_error_code = provider_error_code
        self.provider_message = provider_message


class EmailAlreadyExists(AuthError):
    """Ya existe una cuenta con ese email."""


class WeakPassword(AuthError):
    """La contraseña no cumple la política de Supabase."""


class InvalidEmail(AuthError):
    """El email no es válido según Supabase."""


class RateLimited(AuthError):
    """Supabase rechazó por límite de tasa (demasiados intentos o emails)."""


class InvalidCredentials(AuthError):
    """Email inexistente o contraseña incorrecta (mismo caso: no se distinguen)."""


class EmailNotConfirmed(AuthError):
    """El email aún no está confirmado; no se puede iniciar sesión todavía."""


class AuthProviderError(AuthError):
    """Fallo del proveedor: red, 5xx, error desconocido, o forma inesperada."""


@dataclass(frozen=True)
class SupabaseSession:
    """Tokens que Supabase entrega cuando el alta o el login abren sesión."""

    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class SignUpResult:
    """Resultado de un alta exitosa en Supabase Auth.

    El usuario SIEMPRE se crea; la sesión es opcional: con "Confirm email"
    activado, Supabase no abre sesión hasta que el usuario confirme el correo.
    ``session is None`` es, por tanto, un estado LEGÍTIMO (confirmación
    pendiente), no un error — la distinción entre ambos casos se hace por la
    presencia de la sesión, sin ambigüedad.
    """

    user_id: str
    email: str
    session: SupabaseSession | None


@dataclass(frozen=True)
class SignInResult:
    """Resultado de un login exitoso: el login SIEMPRE abre sesión."""

    user_id: str
    email: str
    session: SupabaseSession


def _require_configured() -> tuple[str, str]:
    """URL + anon key, o falla claro si Supabase Auth no está configurado."""
    if settings.supabase_url is None or settings.supabase_anon_key is None:
        raise AuthProviderError(
            "Supabase Auth no está configurado (ROVER_SUPABASE_URL / "
            "ROVER_SUPABASE_ANON_KEY); ver .env.example."
        )
    return settings.supabase_url, settings.supabase_anon_key.get_secret_value()


async def _gotrue_post(
    path: str, payload: dict[str, str], *, params: dict[str, str] | None = None
) -> dict[str, Any]:
    """POST a un endpoint de GoTrue (ANON key) y devuelve el cuerpo 2xx como dict.

    Concentra el transporte y el manejo de errores comunes a ``sign_up`` y
    ``sign_in``: traduce los ``>= 400`` por ``error_code`` y trata la red caída
    o una respuesta sin JSON como ``AuthProviderError``, sin filtrar el cuerpo
    crudo de Supabase al llamador.
    """
    base_url, anon_key = _require_configured()

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                path,
                params=params or {},
                json=payload,
                # apikey identifica el proyecto ante el gateway de Supabase;
                # Authorization: Bearer con la misma anon key es lo que
                # exige ese gateway (Kong) para dejar pasar la petición.
                headers={"apikey": anon_key, "Authorization": f"Bearer {anon_key}"},
            )
    except httpx.HTTPError as exc:
        raise AuthProviderError("No se pudo contactar a Supabase Auth.") from exc

    try:
        body: Any = response.json()
    except ValueError:
        body = None

    if response.status_code >= 400:
        if isinstance(body, dict):
            raise _translate_error(body, response.status_code)
        # Error sin cuerpo JSON (p. ej. un 5xx del gateway): no hay error_code
        # que traducir; se conserva el status para el log.
        raise AuthProviderError(
            "Supabase Auth respondió con un error.", provider_status=response.status_code
        )

    if not isinstance(body, dict):
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.")
    return body


async def sign_up(email: str, password: str) -> SignUpResult:
    """Registra un usuario en Supabase Auth (ANON key) y devuelve el resultado.

    El resultado distingue el alta CON sesión (confirmación desactivada) del
    alta SIN sesión (confirmación de email pendiente) — ambos son éxitos.
    """
    body = await _gotrue_post(_SIGNUP_PATH, {"email": email, "password": password})
    return _parse_signup(body)


async def sign_in(email: str, password: str) -> SignInResult:
    """Inicia sesión en Supabase Auth (ANON key) y devuelve usuario + sesión.

    Delega en el endpoint de token de GoTrue con ``grant_type=password``. Los
    errores (credenciales inválidas, email sin confirmar, rate limit) se
    traducen a excepciones de dominio por ``error_code``.
    """
    body = await _gotrue_post(
        _TOKEN_PATH, {"email": email, "password": password}, params={"grant_type": "password"}
    )
    return _parse_signin(body)


# error_code de GoTrue → (excepción de dominio, mensaje SEGURO para el cliente).
# La traducción se basa en ``error_code`` (identificador ESTABLE del proveedor),
# NUNCA en buscar palabras dentro de ``msg``: ese texto cambia entre versiones,
# está localizado, y clasificaba mal — un 429 "email rate limit exceeded" caía
# en InvalidEmail solo por contener la palabra "email".
_ERROR_CODE_TO_DOMAIN: dict[str, tuple[type[AuthError], str]] = {
    "email_exists": (EmailAlreadyExists, "Ya existe una cuenta con ese email."),
    "user_already_exists": (EmailAlreadyExists, "Ya existe una cuenta con ese email."),
    "weak_password": (WeakPassword, "La contraseña no cumple los requisitos mínimos."),
    "email_address_invalid": (InvalidEmail, "El email no es válido."),
    "over_email_send_rate_limit": (
        RateLimited,
        "Demasiados intentos; prueba de nuevo en unos minutos.",
    ),
    "over_request_rate_limit": (
        RateLimited,
        "Demasiados intentos; prueba de nuevo en unos minutos.",
    ),
    # --- Login (HU-1.4) ------------------------------------------------------
    # Mensaje idéntico para email inexistente y contraseña incorrecta: no se
    # revela cuál de los dos falló (evita enumerar cuentas).
    "invalid_credentials": (InvalidCredentials, "Email o contraseña incorrectos."),
    "email_not_confirmed": (
        EmailNotConfirmed,
        "Debes confirmar tu correo antes de iniciar sesión.",
    ),
}


def _translate_error(body: dict[str, Any], status_code: int) -> AuthError:
    """Traduce un error de GoTrue a excepción de dominio por ``error_code`` + status.

    NUNCA adivina por el texto del mensaje. Si el ``error_code`` no se
    reconoce, cae en el status HTTP (429 → RateLimited) y, en último término,
    en ``AuthProviderError`` conservando el ``error_code`` para los logs.
    """
    error_code = str(body.get("error_code") or body.get("code") or "")
    provider_message = str(body.get("msg") or body.get("message") or "")

    mapped = _ERROR_CODE_TO_DOMAIN.get(error_code)
    if mapped is not None:
        exc_class, client_message = mapped
        return exc_class(
            client_message,
            provider_status=status_code,
            provider_error_code=error_code,
            provider_message=provider_message,
        )

    # Sin error_code reconocible: el status es la única otra señal fiable.
    if status_code == 429:
        return RateLimited(
            "Demasiados intentos; prueba de nuevo en unos minutos.",
            provider_status=status_code,
            provider_error_code=error_code or None,
            provider_message=provider_message,
        )

    return AuthProviderError(
        "Supabase Auth rechazó la solicitud.",
        provider_status=status_code,
        provider_error_code=error_code or None,
        provider_message=provider_message,
    )


def _extract_user(candidate: Any) -> dict[str, Any] | None:
    """Devuelve ``candidate`` si tiene la forma mínima de un usuario de GoTrue
    (``id`` + ``email`` como strings); si no, ``None``."""
    if (
        isinstance(candidate, dict)
        and isinstance(candidate.get("id"), str)
        and isinstance(candidate.get("email"), str)
    ):
        return candidate
    return None


def _parse_user_and_session(body: Any) -> tuple[str, str, SupabaseSession | None]:
    """Extrae ``(user_id, email, session|None)`` de un cuerpo 2xx de GoTrue.

    Soporta el usuario anidado bajo ``"user"`` o directamente en la raíz. La
    presencia de ``"user"`` es el discriminante PRIMARIO; la raíz (al menos
    ``id`` + ``email``) es el respaldo. Si ``"user"`` está pero es inválido,
    NO se cae al respaldo: es incoherente. Sin usuario identificable →
    ``AuthProviderError``.

    Sesión: ambos tokens → sesión; ningún token → ``None``; un solo token →
    respuesta incoherente (``AuthProviderError``). Que ``None`` sea válido o no
    lo decide cada llamador (alta vs. login).
    """
    if not isinstance(body, dict):
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.")

    raw_user = body.get("user") if "user" in body else body
    user = _extract_user(raw_user)
    if user is None:
        raise AuthProviderError("Respuesta de Supabase Auth sin usuario.")

    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")

    if isinstance(access_token, str) and isinstance(refresh_token, str):
        session: SupabaseSession | None = SupabaseSession(
            access_token=access_token, refresh_token=refresh_token
        )
    elif not access_token and not refresh_token:
        session = None
    else:
        # Un token sí y el otro no: la respuesta del proveedor es incoherente.
        raise AuthProviderError("Supabase Auth devolvió una sesión incompleta.")

    return user["id"], user["email"], session


def _parse_signup(body: Any) -> SignUpResult:
    """Resultado del 2xx de ``/auth/v1/signup``.

    La sesión es OPCIONAL: ambos tokens → alta con sesión (active); ningún
    token con usuario válido → sin sesión (confirmación de email pendiente,
    estado legítimo del negocio, HU-1.3b).
    """
    user_id, email, session = _parse_user_and_session(body)
    return SignUpResult(user_id=user_id, email=email, session=session)


def _parse_signin(body: Any) -> SignInResult:
    """Resultado del 2xx del endpoint de token (login).

    A diferencia del alta, el login SIEMPRE debe abrir sesión: un 2xx sin
    tokens es una respuesta incoherente, no un estado del negocio.
    """
    user_id, email, session = _parse_user_and_session(body)
    if session is None:
        raise AuthProviderError("Supabase Auth no devolvió una sesión en el login.")
    return SignInResult(user_id=user_id, email=email, session=session)
