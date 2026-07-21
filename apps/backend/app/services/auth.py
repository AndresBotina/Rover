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
    """Error de autenticación ya traducido: la capa de API nunca ve la forma de Supabase."""


class EmailAlreadyExists(AuthError):
    """Ya existe una cuenta con ese email."""


class WeakPassword(AuthError):
    """La contraseña no cumple la política de Supabase."""


class InvalidEmail(AuthError):
    """El email no es válido según Supabase."""


class AuthProviderError(AuthError):
    """Fallo del proveedor: red, 5xx, o una respuesta con forma inesperada."""


@dataclass(frozen=True)
class SupabaseSession:
    """Sesión que Supabase entrega tras un alta o login exitosos."""

    user_id: str
    email: str
    access_token: str
    refresh_token: str


def _require_configured() -> tuple[str, str]:
    """URL + anon key, o falla claro si Supabase Auth no está configurado."""
    if settings.supabase_url is None or settings.supabase_anon_key is None:
        raise AuthProviderError(
            "Supabase Auth no está configurado (ROVER_SUPABASE_URL / "
            "ROVER_SUPABASE_ANON_KEY); ver .env.example."
        )
    return settings.supabase_url, settings.supabase_anon_key.get_secret_value()


async def sign_up(email: str, password: str) -> SupabaseSession:
    """Registra un usuario en Supabase Auth (ANON key) y devuelve su sesión.

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

    if response.status_code >= 500:
        raise AuthProviderError("Supabase Auth respondió con un error del servidor.")

    try:
        body: Any = response.json()
    except ValueError as exc:
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.") from exc

    if response.status_code >= 400:
        raise _translate_error(body)

    return _parse_session(body)


def _translate_error(body: Any) -> AuthError:
    """Mapea el error de GoTrue (código + mensaje) a una excepción de dominio.

    GoTrue no tiene un único formato estable de error entre versiones: unas
    traen ``error_code`` (p. ej. ``user_already_exists``), otras solo ``msg``.
    Por eso el matching es por palabras clave sobre ambos campos combinados,
    no por un código exacto.
    """
    code = ""
    message = ""
    if isinstance(body, dict):
        code = str(body.get("error_code") or "")
        message = str(body.get("msg") or body.get("message") or "")
    texto = f"{code} {message}".lower()

    if "already" in texto or "exists" in texto or "registered" in texto:
        return EmailAlreadyExists("Ya existe una cuenta con ese email.")
    if "password" in texto:
        return WeakPassword("La contraseña no cumple los requisitos mínimos.")
    if "email" in texto:
        return InvalidEmail("El email no es válido.")
    return AuthProviderError("Supabase Auth rechazó la solicitud.")


def _parse_session(body: Any) -> SupabaseSession:
    """Extrae la sesión del cuerpo 2xx de ``/auth/v1/signup``."""
    if not isinstance(body, dict):
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.")

    user = body.get("user")
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")

    if (
        not isinstance(user, dict)
        or not isinstance(access_token, str)
        or not isinstance(refresh_token, str)
    ):
        # Con "Confirm email" activado en el proyecto, Supabase crea el
        # usuario pero NO abre sesión hasta que confirme el correo (el 2xx
        # llega sin tokens). Fuera de alcance de esta HU: asume esa opción
        # desactivada. Lo tratamos como fallo del proveedor en vez de
        # inventar una sesión que no existe.
        raise AuthProviderError(
            "Supabase Auth no devolvió una sesión (¿confirmación de email activada?)."
        )

    user_id = user.get("id")
    email = user.get("email")
    if not isinstance(user_id, str) or not isinstance(email, str):
        raise AuthProviderError("Respuesta de Supabase Auth con forma inesperada.")

    return SupabaseSession(
        user_id=user_id,
        email=email,
        access_token=access_token,
        refresh_token=refresh_token,
    )
