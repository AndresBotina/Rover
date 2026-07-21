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


def _require_configured() -> tuple[str, str]:
    """URL + anon key, o falla claro si Supabase Auth no está configurado."""
    if settings.supabase_url is None or settings.supabase_anon_key is None:
        raise AuthProviderError(
            "Supabase Auth no está configurado (ROVER_SUPABASE_URL / "
            "ROVER_SUPABASE_ANON_KEY); ver .env.example."
        )
    return settings.supabase_url, settings.supabase_anon_key.get_secret_value()


async def sign_up(email: str, password: str) -> SignUpResult:
    """Registra un usuario en Supabase Auth (ANON key) y devuelve el resultado.

    El resultado distingue el alta CON sesión (confirmación desactivada) del
    alta SIN sesión (confirmación de email pendiente) — ambos son éxitos.
    Traduce los errores conocidos de GoTrue a las excepciones de arriba;
    cualquier otra cosa (red caída, 5xx, forma de respuesta inesperada) se
    convierte en ``AuthProviderError`` SIN filtrar el cuerpo crudo de
    Supabase al llamador (puede traer detalles internos del proveedor).
    """
    base_url, anon_key = _require_configured()

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _SIGNUP_PATH,
                json={"email": email, "password": password},
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

    if body is None:
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.")

    return _parse_signup(body)


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


def _parse_signup(body: Any) -> SignUpResult:
    """Extrae el resultado del cuerpo 2xx de ``/auth/v1/signup``.

    El USUARIO es obligatorio: sin él la respuesta es incoherente y se trata
    como ``AuthProviderError``. La SESIÓN es opcional: si vienen ambos tokens,
    hay sesión; si no viene ninguno, es una alta con confirmación de email
    pendiente (estado válido). Un solo token (uno sí y otro no) es una
    respuesta incoherente, no un estado del negocio.
    """
    if not isinstance(body, dict):
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.")

    user = body.get("user")
    if not isinstance(user, dict):
        raise AuthProviderError("Respuesta de Supabase Auth sin usuario.")

    user_id = user.get("id")
    email = user.get("email")
    if not isinstance(user_id, str) or not isinstance(email, str):
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.")

    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")

    if isinstance(access_token, str) and isinstance(refresh_token, str):
        session: SupabaseSession | None = SupabaseSession(
            access_token=access_token, refresh_token=refresh_token
        )
    elif not access_token and not refresh_token:
        # "Confirm email" activado: usuario creado, sesión pendiente de que
        # confirme el correo. Estado LEGÍTIMO del negocio (HU-1.3b).
        session = None
    else:
        # Un token sí y el otro no: la respuesta del proveedor es incoherente.
        raise AuthProviderError("Supabase Auth devolvió una sesión incompleta.")

    return SignUpResult(user_id=user_id, email=email, session=session)
