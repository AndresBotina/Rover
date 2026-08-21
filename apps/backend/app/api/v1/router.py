"""Router agregador de la versión **v1** de la API.

Punto ÚNICO donde se monta `/v1`: los routers de dominio (``health``,
``auth``, ``users``, ``chat``) se declaran sin versión y este módulo les pone
el prefijo.
Así ``main.py`` no conoce los dominios uno por uno, y publicar una futura
``/v2`` es añadir otro agregador en vez de tocar cada `include_router`.

Aquí vive también la descripción de los TAGS de OpenAPI: el orden de esta
lista es el orden en que aparecen las secciones en `/docs`.
"""

from typing import Any

from fastapi import APIRouter

from app.api.v1 import auth, chat, health, users

# Prefijo de versión en un solo sitio (los routers de dominio no lo repiten).
API_V1_PREFIX = "/v1"

# Metadatos de los tags: dan a cada sección de /docs un texto que explica de
# qué va el dominio. El orden manda en la UI.
TAGS_METADATA: list[dict[str, Any]] = [
    {
        "name": "health",
        "description": (
            "Sondas de estado del servicio. `GET /v1/health` es el healthcheck "
            "que usa Render para decidir si un deploy quedó sano; "
            "`GET /v1/health/db` verifica además la conectividad con la base."
        ),
    },
    {
        "name": "auth",
        "description": (
            "Registro y login, **delegados en Supabase Auth**: el backend no "
            "firma JWT propios, valida los que emite Supabase. Las respuestas "
            "traen la sesión de Supabase (access + refresh token); el access "
            "token es el que viaja en `Authorization: Bearer` hacia las rutas "
            "protegidas."
        ),
    },
    {
        "name": "users",
        "description": (
            "Perfil del usuario autenticado. El id **siempre** sale del token "
            "(por eso la ruta es `/me` y no `/users/{id}`): nadie puede "
            "nombrar el recurso de otro. Es también el endpoint de identidad: "
            "responde *quién soy* además de *cuál es mi perfil*."
        ),
    },
    {
        "name": "chat",
        "description": (
            "Conversación con Rover. `POST /v1/chat` responde en **streaming "
            "(SSE)**: el cuerpo no es un JSON sino una secuencia de eventos "
            "`data: {...}` discriminados por `type`. La conversación queda "
            "persistida, y su dueño es **siempre** el usuario del token."
        ),
    },
]

router = APIRouter(prefix=API_V1_PREFIX)
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(chat.router)
