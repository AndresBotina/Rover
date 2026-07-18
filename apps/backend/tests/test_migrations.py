"""Tests de la configuración de Alembic — SIN base real (CI sin Supabase).

Solo validan configuración y estructura de revisiones; aplicar migraciones de
verdad se hace a mano contra Supabase (ver README, sección Migraciones).
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND = Path(__file__).resolve().parents[1]


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_BACKEND / "alembic.ini")))


def test_la_configuracion_de_alembic_carga() -> None:
    """alembic.ini + migrations/ resuelven sin tocar la base."""
    script = _script_directory()

    assert (Path(script.dir) / "env.py").is_file()


def test_una_sola_head_y_baseline_sin_padre() -> None:
    """Historia lineal: una única head, y la baseline arranca desde cero."""
    script = _script_directory()

    heads = script.get_heads()
    assert len(heads) == 1

    baseline = script.get_revision(heads[0])
    assert baseline.down_revision is None


def test_alembic_ini_no_contiene_la_url_de_la_base() -> None:
    """La URL es un SECRETO: vive en ROVER_DATABASE_URL, jamás en el ini."""
    contenido = (_BACKEND / "alembic.ini").read_text(encoding="utf-8")

    assert "sqlalchemy.url" not in contenido
    assert "postgresql://" not in contenido
