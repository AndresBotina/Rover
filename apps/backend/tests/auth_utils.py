"""Utilidades de test para autenticación: firma tokens ES256 e inyecta el JWKS.

NO es un archivo de tests (sin ``test_``): lo importan los módulos que ejercen
rutas protegidas, para no depender del JWKS ni de credenciales reales.
"""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core import security
from app.core.config import settings

SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
AUDIENCE = "authenticated"
KID = "test-kid"

# Par de claves ES256 de prueba, generado una vez por proceso de test.
PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


def jwks_set() -> jwt.PyJWKSet:
    """JWKS con la clave PÚBLICA de prueba (kid = KID)."""
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(PRIVATE_KEY.public_key()))
    jwk.update({"kid": KID, "alg": "ES256", "use": "sig"})
    return jwt.PyJWKSet.from_dict({"keys": [jwk]})


def install_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura la URL de Supabase, inyecta el JWKS de prueba y aísla la caché."""
    monkeypatch.setattr(settings, "supabase_url", SUPABASE_URL)

    async def fake_fetch() -> jwt.PyJWKSet:
        return jwks_set()

    monkeypatch.setattr(security, "_fetch_jwks", fake_fetch)
    security.reset_jwks_cache()


def make_token(*, sub: str, email: str = "viajera@example.com", exp_delta: int = 3600) -> str:
    """Firma un access token ES256 válido para el proyecto de prueba."""
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": sub,
        "email": email,
        "exp": int(time.time()) + exp_delta,
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm="ES256", headers={"kid": KID})
