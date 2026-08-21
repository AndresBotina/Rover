/**
 * Tipos de las sesiones de chat (`/v1/chat/sessions`).
 *
 * Espejo de apps/backend/app/api/v1/sessions.py.
 *
 * ## El historial es SOLO texto conversacional, y eso es un tipo, no una regla
 *
 * `ChatSessionMessage` declara `role`, `content`, `sequence` y `created_at`, y
 * nada más. Los `tool_steps` (los pasos intermedios de tool-calling que el
 * backend guarda desde la HU-2.3) **no están en el tipo**, así que un cliente
 * no puede ni esperarlos ni pintarlos por descuido: el compilador se lo impide
 * antes de que exista la pantalla donde aparecerían. Es la misma defensa que
 * `ProfileUpdate` monta contra `plan`.
 */

/** Cabecera de una conversación: lo justo para pintar una lista. */
export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: string;
  /**
   * Momento del último mensaje. Es la clave por la que el backend ordena la
   * lista (de la más activa a la más vieja) y, cuando haga falta paginar, el
   * cursor natural.
   */
  updated_at: string;
}

/**
 * Lista de conversaciones vivas del usuario.
 *
 * Objeto y no array pelado para poder ganar campos de paginación sin romper a
 * los clientes ya publicados. Si `items.length === limit`, puede haber más.
 */
export interface ChatSessionList {
  items: ChatSessionSummary[];
  limit: number;
}

/** Quién habla en un turno guardado. `system` no se persiste (es un archivo). */
export type ChatRole = "user" | "assistant";

/** Un turno del historial: texto conversacional y su posición. */
export interface ChatSessionMessage {
  role: ChatRole;
  content: string;
  /**
   * Posición dentro del hilo. Es el orden REAL: no hay que confiar en que la
   * lista llegó ordenada ni desempatar por `created_at`, que para dos mensajes
   * escritos en la misma transacción es el mismo instante.
   */
  sequence: number;
  created_at: string;
}

/** Una conversación con su historial completo, en orden. */
export interface ChatSession extends ChatSessionSummary {
  messages: ChatSessionMessage[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isSummaryShape(v: Record<string, unknown>): boolean {
  return (
    typeof v["id"] === "string" &&
    typeof v["title"] === "string" &&
    typeof v["created_at"] === "string" &&
    typeof v["updated_at"] === "string"
  );
}

/** Type guard de la cabecera de una conversación. */
export function isChatSessionSummary(value: unknown): value is ChatSessionSummary {
  const v = asRecord(value);
  return v !== null && isSummaryShape(v);
}

/** Type guard de un turno del historial. */
export function isChatSessionMessage(value: unknown): value is ChatSessionMessage {
  const v = asRecord(value);
  return (
    v !== null &&
    (v["role"] === "user" || v["role"] === "assistant") &&
    typeof v["content"] === "string" &&
    typeof v["sequence"] === "number" &&
    typeof v["created_at"] === "string"
  );
}

/** Type guard de la lista de conversaciones. */
export function isChatSessionList(value: unknown): value is ChatSessionList {
  const v = asRecord(value);
  return (
    v !== null &&
    Array.isArray(v["items"]) &&
    v["items"].every(isChatSessionSummary) &&
    typeof v["limit"] === "number"
  );
}

/** Type guard de una conversación con su historial. */
export function isChatSession(value: unknown): value is ChatSession {
  const v = asRecord(value);
  return (
    v !== null &&
    isSummaryShape(v) &&
    Array.isArray(v["messages"]) &&
    v["messages"].every(isChatSessionMessage)
  );
}
