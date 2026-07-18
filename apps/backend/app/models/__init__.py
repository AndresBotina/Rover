"""Modelos de dominio (SQLAlchemy).

Importar este paquete registra TODAS las tablas en ``Base.metadata``: es lo
que ``migrations/env.py`` importa para que ``--autogenerate`` las vea. Un
modelo nuevo debe importarse aquí o Alembic no lo detectará.
"""

from app.models.user import Plan, UserProfile

__all__ = ["Plan", "UserProfile"]
