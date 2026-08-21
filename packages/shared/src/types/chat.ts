/**
 * Tipos del chat en streaming (POST /v1/chat).
 *
 * Espejo del endpoint del backend (apps/backend/app/api/v1/chat.py) y de su
 * formato de eventos (app/api/sse.py).
 *
 * A diferencia del resto de la API, la respuesta no es un JSON: es una
 * secuencia de eventos SSE que llegan mientras el modelo escribe. Lo que web y
 * móvil necesitan de aquí es poder saber, sin adivinar, si lo que acaba de
 * llegar es texto para pintar o un fallo que mostrar — y por eso los eventos
 * son una **unión discriminada** por `type`, con un type guard por variante,
 * igual que el contrato de registro de la HU-1.3b.
 */

import { isApiErrorResponse, type ApiErrorBody } from "./error.ts";

/** Cuerpo de POST /v1/chat. */
export interface ChatRequest {
  /** Lo que el usuario le dice a Rover. Entre 1 y 8000 caracteres ya recortados. */
  message: string;
  /**
   * Conversación existente a continuar. Omitir (o `null`) crea una nueva.
   *
   * Que el backend lo acepte NO da acceso: comprueba contra el usuario del
   * token y responde 404 si la conversación no es suya, no existe o está
   * borrada — los tres casos con la misma respuesta, para que el id no sirva
   * de oráculo. El dueño **nunca** viaja en el cuerpo.
   */
  conversation_id?: string | null;
}

/**
 * Primer evento del stream: dice a qué conversación pertenece lo que sigue.
 *
 * Llega siempre, también al continuar una conversación. `created` distingue
 * "esta conversación acaba de nacer" (añádela a la lista lateral) de "es la
 * que ya tenías abierta".
 */
export interface ChatStartEvent {
  type: "start";
  conversation_id: string;
  created: boolean;
}

/**
 * Un trozo de la respuesta. `text` es el DELTA, no el acumulado: concatenar
 * los `text` en orden reconstruye la respuesta completa.
 */
export interface ChatDeltaEvent {
  type: "delta";
  text: string;
}

/**
 * Fin correcto. Solo llega si la respuesta se completó — que es exactamente
 * cuando el backend la persiste. `sequence` es la posición del mensaje del
 * asistente dentro de la conversación.
 */
export interface ChatDoneEvent {
  type: "done";
  sequence: number;
}

/**
 * Fallo **a mitad** del stream. El status HTTP ya se envió (fue 200), así que
 * el error viaja por aquí con el MISMO cuerpo que tendría en HTTP: se ramifica
 * por `error.code`, del mismo catálogo de siempre.
 *
 * Un fallo ANTES del stream no llega como este evento: llega como un error
 * HTTP normal y `streamChat` lo lanza como `ApiError`.
 */
export interface ChatErrorEvent {
  type: "error";
  error: ApiErrorBody;
}

/** Cualquier evento del stream de chat. Discriminado por `type`. */
export type ChatStreamEvent = ChatStartEvent | ChatDeltaEvent | ChatDoneEvent | ChatErrorEvent;

/** Type guard de un evento `start`. */
export function isChatStartEvent(value: unknown): value is ChatStartEvent {
  const v = asRecord(value);
  return (
    v !== null &&
    v["type"] === "start" &&
    typeof v["conversation_id"] === "string" &&
    typeof v["created"] === "boolean"
  );
}

/** Type guard de un trozo de texto. */
export function isChatDeltaEvent(value: unknown): value is ChatDeltaEvent {
  const v = asRecord(value);
  return v !== null && v["type"] === "delta" && typeof v["text"] === "string";
}

/** Type guard del fin correcto. */
export function isChatDoneEvent(value: unknown): value is ChatDoneEvent {
  const v = asRecord(value);
  return v !== null && v["type"] === "done" && typeof v["sequence"] === "number";
}

/** Type guard del error a mitad de stream. */
export function isChatErrorEvent(value: unknown): value is ChatErrorEvent {
  const v = asRecord(value);
  // Reutiliza el guard del contrato de errores envolviendo el cuerpo: si algún
  // día ese contrato gana un campo, esta validación lo hereda sin tocarse.
  return v !== null && v["type"] === "error" && isApiErrorResponse({ error: v["error"] });
}

/**
 * Type guard de cualquier evento del stream.
 *
 * Es deliberadamente ESTRICTO: un `type` que este cliente no conoce devuelve
 * `false` y `streamChat` lo descarta. Es lo contrario de `ApiErrorCode`, que sí
 * admite códigos futuros — allí el cliente solo tiene que MOSTRAR un mensaje
 * que ya viene hecho, mientras que aquí tendría que saber qué hacer con la
 * carga útil de un evento que no existía cuando se compiló.
 */
export function isChatStreamEvent(value: unknown): value is ChatStreamEvent {
  return (
    isChatStartEvent(value) ||
    isChatDeltaEvent(value) ||
    isChatDoneEvent(value) ||
    isChatErrorEvent(value)
  );
}

/**
 * Parsea el contenido de un marco SSE (lo que va tras `data:`) a un evento
 * tipado, o `null` si no es JSON válido o no es un evento conocido.
 *
 * Devolver `null` en vez de lanzar es intencional y es la misma política que
 * el backend aplica con los eventos ilegibles del proveedor: una respuesta a
 * medias en pantalla vale más que un corte por un marco roto.
 */
export function parseChatStreamEvent(data: string): ChatStreamEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data) as unknown;
  } catch {
    return null;
  }
  return isChatStreamEvent(parsed) ? parsed : null;
}

/**
 * Trocea un stream de texto SSE en los payloads de sus marcos `data:`.
 *
 * Es un parser mínimo del formato, no un `EventSource`: solo entiende `data:`
 * (que es lo único que este backend emite, ver app/api/sse.py) e ignora
 * comentarios de keep-alive (`:`) y cualquier otro campo. Existe porque
 * `EventSource` no sirve para este endpoint: solo sabe hacer GET y no deja
 * poner cabeceras, así que no podría mandar ni el mensaje ni el
 * `Authorization: Bearer`.
 *
 * Los marcos se separan por una línea en blanco y un chunk de red puede cortar
 * uno por la mitad; por eso el resto incompleto se guarda hasta el chunk
 * siguiente en vez de descartarse.
 */
export async function* readSseFrames(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<string, void, undefined> {
  const decoder = new TextDecoder();
  const reader = stream.getReader();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      // `stream: true` mantiene a medias los caracteres multibyte partidos
      // entre dos chunks: sin él, un acento en la frontera saldría como "�".
      buffer += decoder.decode(value, { stream: true });

      // \r\n además de \n: el formato lo admite y un proxy podría reescribirlo.
      let corte = findFrameEnd(buffer);
      while (corte !== null) {
        const marco = buffer.slice(0, corte.index);
        buffer = buffer.slice(corte.index + corte.length);
        const payload = dataOf(marco);
        if (payload !== null) {
          yield payload;
        }
        corte = findFrameEnd(buffer);
      }
    }
    // Un último marco sin línea en blanco final (el servidor cerró justo
    // después) sigue siendo un marco válido.
    const payload = dataOf(buffer);
    if (payload !== null) {
      yield payload;
    }
  } finally {
    // Suelta la conexión aunque quien consume abandone el bucle a mitad — el
    // caso normal cuando el usuario cierra la vista del chat.
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

/** Posición y largo del separador de marcos (línea en blanco), o `null`. */
function findFrameEnd(buffer: string): { index: number; length: number } | null {
  const lf = buffer.indexOf("\n\n");
  const crlf = buffer.indexOf("\r\n\r\n");
  if (lf === -1 && crlf === -1) {
    return null;
  }
  if (crlf !== -1 && (lf === -1 || crlf < lf)) {
    return { index: crlf, length: 4 };
  }
  return { index: lf, length: 2 };
}

/**
 * Junta las líneas `data:` de un marco, o `null` si el marco no trae ninguna.
 *
 * El estándar une varias líneas `data:` con `\n`. Este backend siempre manda
 * una sola (el JSON no lleva saltos de línea reales), pero soportarlo cuesta
 * una línea y evita que un intermediario que reparta el payload rompa el
 * cliente.
 */
function dataOf(marco: string): string | null {
  const partes: string[] = [];
  for (const linea of marco.split(/\r?\n/)) {
    if (linea.startsWith("data:")) {
      partes.push(linea.slice("data:".length).replace(/^ /, ""));
    }
  }
  return partes.length === 0 ? null : partes.join("\n");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
