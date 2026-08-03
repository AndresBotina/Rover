"""Fixtures compartidas por toda la suite.

Existe desde la HU-1.7: el rate limiting cuenta en un almacén de proceso que
sobrevive entre tests, así que sin reiniciarlo un módulo agotaría el cupo del
siguiente y haría fallar tests que no tienen nada que ver con los límites.
"""

import pytest

from app.core.rate_limit import reset_rate_limit_store


@pytest.fixture(autouse=True)
def rate_limit_aislado() -> None:
    """Cada test arranca con el contador de peticiones vacío."""
    reset_rate_limit_store()
