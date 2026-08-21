"""Modelos de dominio (SQLAlchemy).

Importar este paquete registra TODAS las tablas en ``Base.metadata``: es lo
que ``migrations/env.py`` importa para que ``--autogenerate`` las vea. Un
modelo nuevo debe importarse aquí o Alembic no lo detectará.
"""

from app.models.conversation import (
    Conversation,
    Message,
    MessageRole,
    select_conversation_messages,
    select_live_conversations,
)
from app.models.user import Plan, UserProfile

__all__ = [
    "Conversation",
    "Message",
    "MessageRole",
    "Plan",
    "UserProfile",
    "select_conversation_messages",
    "select_live_conversations",
]
