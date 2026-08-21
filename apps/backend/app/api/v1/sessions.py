"""Sesiones de chat: listar, leer y borrar conversaciones (`/v1/chat/sessions`).

Van en su propio módulo y no junto a `POST /v1/chat` porque son otra cosa: allí
hay un stream, un proveedor de LLM y persistencia a mitad de vuelo; aquí hay
tres lecturas de base de datos y un soft-delete. Comparten el router —y por
tanto el prefijo, la cuota y el tag— pero no el problema.


## Lo que se expone y lo que NO

El historial de una conversación devuelve **solo el texto conversacional**:
`role`, `content`, `sequence` y `created_at`. Los ``tool_steps`` (HU-2.3) **no
aparecen**, y no por un filtro que alguien tenga que acordarse de aplicar: el
modelo de respuesta **no declara ese campo**, así que no hay nada que filtrar.
Es la misma defensa que ``ProfileUpdate`` con ``plan`` — lo que no está en el
tipo no puede escaparse por descuido.

Que la frontera esté en el TIPO y no en la disciplina importa aquí más que en
otros sitios: los pasos intermedios llevan respuestas crudas de APIs de
terceros y son exactamente la clase de dato que nadie revisa hasta que aparece
en la pantalla de alguien.


## Por qué todo lo ajeno responde 404

"No existe", "es de otra persona" y "está en la papelera" dan **la misma
respuesta**, byte a byte. Un 403 para la ajena confirmaría que ese id existe y
convertiría estos endpoints en un oráculo para enumerar UUIDs. Y los tres casos
no coinciden por disciplina: colapsan dentro de la CONSULTA
(``chat.load_conversation`` sobre ``select_live_conversations``, que ya filtra
``deleted_at IS NULL``), así que un refactor no puede separarlos sin querer.
Mismo criterio que el `POST /v1/chat` de la HU-2.4 y que el `/users/me` de la
HU-1.9.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import CursorResult, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AUTH_RESPONSES,
    CurrentUser,
    enforce_user_rate_limit,
    get_current_user,
)
from app.core.database import get_db
from app.core.errors import ApiError, ErrorCode, error_doc
from app.models import Conversation, MessageRole, select_live_conversations
from app.services import chat

router = APIRouter(
    prefix="/chat/sessions",
    tags=["chat"],
    # Misma disciplina que ``users`` y que el chat: la cuota por usuario
    # (HU-1.7) se declara a nivel de ROUTER, así una ruta nueva nace con
    # límite en vez de olvidarlo.
    dependencies=[Depends(enforce_user_rate_limit)],
)

#: Cuántas conversaciones devuelve la lista si no se pide otra cosa, y el techo
#: duro. La lista es la barra lateral del chat: 50 conversaciones recientes es
#: más de lo que nadie recorre de un vistazo, y el techo impide que un cliente
#: se pida la historia entera de una cuenta en una sola respuesta.
_LIMITE_POR_DEFECTO = 50
_LIMITE_MAXIMO = 100

_NO_ENCONTRADA = "No encontramos esa conversación."


def _no_encontrada() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, _NO_ENCONTRADA)


class SessionSummary(BaseModel):
    """Cabecera de una conversación: lo justo para pintarla en una lista."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "0f6c2f9e-1f2a-4c3b-9d5e-8a7b6c5d4e3f",
                    "title": "¿Qué hago tres días en Medellín?",
                    "created_at": "2026-08-20T15:04:05Z",
                    "updated_at": "2026-08-20T15:11:22Z",
                }
            ]
        },
    )

    id: uuid.UUID
    title: str
    created_at: datetime
    #: Momento del ÚLTIMO mensaje, no de la última edición del título: cada
    #: mensaje toca la conversación (HU-2.5). Es la clave de orden de la lista
    #: y, el día que haga falta paginar, el cursor natural — el ``id`` la
    #: desempata en la consulta, que es lo que hace viable esa paginación.
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Lista de conversaciones vivas, de la más activa a la más vieja.

    Envuelta en un objeto y no devuelta como array pelado: así se le pueden
    añadir campos de paginación (un cursor, un total) sin romper a ningún
    cliente ya publicado. Hoy no hay cursor a propósito —fijarlo ahora sería
    decidir el contrato antes de saber si la web quiere scroll infinito o una
    pantalla de "ver todas"—, y `updated_at` ya es la clave por la que se
    haría (paginación por keyset, no por OFFSET, que se descoloca cuando
    llega un mensaje mientras se pagina).
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [], "limit": _LIMITE_POR_DEFECTO}]}
    )

    items: list[SessionSummary]
    #: El límite que se aplicó. Si `len(items) == limit` puede haber más.
    limit: int


class SessionMessage(BaseModel):
    """Un turno, tal como se le muestra al cliente: SOLO texto conversacional.

    No declara ``tool_steps``. Esa ausencia es el mecanismo, no un olvido: ver
    el docstring del módulo.
    """

    model_config = ConfigDict(from_attributes=True)

    role: MessageRole
    content: str
    #: La posición dentro del hilo (HU-2.3). Se expone porque es el orden real
    #: y estable de la conversación: el cliente no tiene que confiar en que la
    #: lista le llegó ordenada ni desempatar por ``created_at``, que para dos
    #: mensajes de la misma transacción es el mismo instante.
    sequence: int
    created_at: datetime


class SessionDetailResponse(SessionSummary):
    """Una conversación con su historial completo, en orden."""

    model_config = ConfigDict(from_attributes=True)

    #: Sin paginar: es UNA conversación y el cliente la necesita entera para
    #: pintar el hilo. Lo que acota el tamaño de verdad es el uso (un chat de
    #: viaje son decenas de turnos, no miles); si algún día deja de ser cierto,
    #: se pagina hacia atrás por ``sequence``, que ya viaja en cada mensaje.
    messages: list[SessionMessage]


@router.get(
    "",
    response_model=SessionListResponse,
    summary="Listar las conversaciones del usuario",
    responses={
        200: {"description": "Conversaciones vivas del dueño del token, de la más reciente."},
        422: error_doc(f"`validation_error` — `limit` fuera de rango (1–{_LIMITE_MAXIMO})."),
        **AUTH_RESPONSES,
    },
)
async def list_sessions(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[
        int,
        Query(ge=1, le=_LIMITE_MAXIMO, description="Cuántas conversaciones devolver."),
    ] = _LIMITE_POR_DEFECTO,
) -> SessionListResponse:
    """Devuelve las conversaciones **vivas** del usuario, por **actividad reciente**.

    Solo la cabecera de cada una (id, título y timestamps): el historial se pide
    conversación por conversación. Devolver los mensajes aquí convertiría pintar
    una barra lateral en descargar todas las conversaciones de la cuenta.

    Las borradas (soft-delete) no aparecen, y las de otras personas tampoco:
    el dueño sale del token.
    """
    consulta = select_live_conversations(user.id).limit(limit)
    filas = (await db.execute(consulta)).scalars().all()
    return SessionListResponse(
        items=[SessionSummary.model_validate(fila) for fila in filas], limit=limit
    )


@router.get(
    "/{session_id}",
    response_model=SessionDetailResponse,
    summary="Historial de una conversación",
    responses={
        200: {"description": "La conversación y sus mensajes, en orden."},
        404: error_doc(
            "`not_found` — no existe, está borrada o es de otra persona. Los "
            "tres casos responden **lo mismo**: distinguirlos convertiría el id "
            "en un oráculo para averiguar qué conversaciones existen."
        ),
        422: error_doc("`validation_error` — `session_id` no es un UUID."),
        **AUTH_RESPONSES,
    },
)
async def get_session(
    session_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionDetailResponse:
    """Devuelve una conversación del usuario con **todos sus mensajes en orden**.

    Solo texto conversacional: `role`, `content`, `sequence` y `created_at`. Los
    pasos intermedios de tool-calling se guardan pero **nunca se exponen**.
    """
    conversacion = await chat.load_conversation(db, user_id=user.id, conversation_id=session_id)
    if conversacion is None:
        raise _no_encontrada()

    mensajes = await chat.load_history(db, conversacion.id)
    return SessionDetailResponse(
        id=conversacion.id,
        title=conversacion.title,
        created_at=conversacion.created_at,
        updated_at=conversacion.updated_at,
        messages=[SessionMessage.model_validate(m) for m in mensajes],
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una conversación",
    responses={
        204: {"description": "Borrada. Sin cuerpo."},
        404: error_doc(
            "`not_found` — no existe, **ya estaba borrada** o es de otra "
            "persona. Los tres responden lo mismo, por la misma razón que en el "
            "GET."
        ),
        422: error_doc("`validation_error` — `session_id` no es un UUID."),
        **AUTH_RESPONSES,
    },
)
async def delete_session(
    session_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Borra una conversación (**soft-delete**: se marca, no se destruye).

    Deja de aparecer en la lista, deja de ser accesible y `POST /v1/chat` con
    ese id responde 404. Los mensajes siguen en la base, que es lo que permite
    una recuperación por soporte y un purgado por retención con fecha (HU-2.3).

    **Borrar dos veces devuelve 404 la segunda**, no 204. Es la tensión
    conocida entre idempotencia y no filtrar: responder 204 a una ya borrada
    diría "ese id existió y era tuyo", que es justo lo que el 404 uniforme
    evita. Para el cliente el desenlace es el mismo —la conversación no está—,
    así que se prefiere no filtrar.
    """
    # El ``cast`` es solo para los tipos: ``AsyncSession.execute`` se declara
    # devolviendo ``Result``, pero una DML siempre entrega un ``CursorResult``,
    # que es el único que sabe cuántas filas tocó.
    resultado = cast(
        "CursorResult[Any]",
        await db.execute(
            update(Conversation)
            .where(
                Conversation.id == session_id,
                Conversation.user_id == user.id,
                Conversation.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        ),
    )
    # Un solo UPDATE condicional en vez de leer-y-luego-escribir: la propia
    # sentencia comprueba la pertenencia y el "sigue viva", así que dos
    # peticiones simultáneas no pueden borrarla dos veces ni colarse entre la
    # lectura y la escritura. ``rowcount == 0`` cubre los tres casos del 404.
    if resultado.rowcount == 0:
        raise _no_encontrada()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Reexportado para que el agregador del router no tenga que conocer los
# nombres internos de este módulo.
__all__ = ["router"]
