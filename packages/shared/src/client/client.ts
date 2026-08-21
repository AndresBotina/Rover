/**
 * Cliente HTTP tipado del backend de Rover.
 *
 * Usa fetch NATIVO (Node ≥ 18, Next.js y React Native lo traen) para no atar
 * el paquete a una librería HTTP. Escrito a mano por ahora: en Épica 1 la idea
 * es generarlo desde el esquema OpenAPI del backend, por eso los tipos viven
 * aparte en ../types y aquí solo hay transporte + validación.
 */

import {
  isLoginResponse,
  isRegisterResponse,
  type LoginRequest,
  type LoginResponse,
  type RegisterRequest,
  type RegisterResponse,
} from "../types/auth.ts";
import {
  isApiErrorResponse,
  parseRetryAfter,
  RATE_LIMITED,
  REQUEST_ID_HEADER,
  type ApiErrorCode,
} from "../types/error.ts";
import {
  parseChatStreamEvent,
  readSseFrames,
  type ChatRequest,
  type ChatStreamEvent,
} from "../types/chat.ts";
import { isProfile, type Profile, type ProfileUpdate } from "../types/profile.ts";
import {
  isChatSession,
  isChatSessionList,
  type ChatSession,
  type ChatSessionList,
} from "../types/session.ts";
import {
  isDbHealthResponse,
  isHealthResponse,
  type DbHealthResponse,
  type HealthResponse,
} from "../types/health.ts";
import { resolveBaseUrl, type ApiClientConfig } from "./config.ts";

/**
 * Error tipado del cliente. Cubre los tres fallos posibles de una llamada:
 * red caída (status null), respuesta no-2xx, o cuerpo con forma inesperada.
 *
 * Cuando el backend responde con su formato único de error, `code`, `details`
 * y `errorId` vienen rellenos y `message` es el del servidor (seguro de
 * mostrar). Si la respuesta no lo trae —un proxy, un balanceador, un fallo de
 * red— quedan en `null` y solo hay `status`.
 */
export class ApiError extends Error {
  /** URL que se estaba llamando. */
  readonly url: string;
  /** Status HTTP de la respuesta, o null si la petición no llegó (fallo de red). */
  readonly status: number | null;
  /** Código estable del backend; null si la respuesta no siguió el formato. */
  readonly code: ApiErrorCode | null;
  /** Detalles estructurados (p. ej. los errores campo a campo de un 422). */
  readonly details: Record<string, unknown> | null;
  /** Identificador de un 500, para reportarlo y cruzarlo con los logs. */
  readonly errorId: string | null;
  /**
   * Segundos a esperar antes de reintentar, leídos de `Retry-After` (HU-1.7).
   * Solo viene con un 429; `null` en cualquier otro error.
   */
  readonly retryAfterSeconds: number | null;
  /**
   * Id de la petición (`X-Request-ID`), presente en CUALQUIER respuesta del
   * backend (HU-1.12). Es lo que permite cruzar lo que vio el usuario con los
   * logs del servidor: conviene mostrarlo o registrarlo al reportar un fallo.
   *
   * Complementa a `errorId` sin sustituirlo: el `errorId` solo existe en los
   * 500 e identifica ESE fallo, mientras que el request id identifica la
   * petición entera y también está en los errores que no son 500 (un 429, un
   * 401) y en las respuestas correctas. En los logs del servidor los dos
   * aparecen juntos en la misma línea.
   */
  readonly requestId: string | null;

  constructor(
    message: string,
    options: {
      url: string;
      status: number | null;
      code?: ApiErrorCode | null;
      details?: Record<string, unknown> | null;
      errorId?: string | null;
      retryAfterSeconds?: number | null;
      requestId?: string | null;
      cause?: unknown;
    },
  ) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.url = options.url;
    this.status = options.status;
    this.code = options.code ?? null;
    this.details = options.details ?? null;
    this.errorId = options.errorId ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
    this.requestId = options.requestId ?? null;
  }
}

/**
 * Type guard del 429: distingue "espera y reintenta" de cualquier otro fallo.
 *
 * Ramifica por `code`, no por `status`, igual que el resto del contrato de
 * errores: el código es lo estable. Cuando devuelve `true`, `retryAfterSeconds`
 * dice cuánto esperar —o es `null` si el servidor no lo indicó, en cuyo caso el
 * cliente decide su propio backoff.
 */
export function isRateLimitedError(
  error: unknown,
): error is ApiError & { code: typeof RATE_LIMITED } {
  return error instanceof ApiError && error.code === RATE_LIMITED;
}

/**
 * Convierte una respuesta no-2xx en ApiError, aprovechando el formato único
 * del backend cuando está presente. Un solo type guard para toda la API.
 */
async function toApiError(url: string, response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = (await response.json()) as unknown;
  } catch {
    body = undefined; // cuerpo vacío o no-JSON (p. ej. un error de proxy)
  }
  // Se lee siempre, no solo en los 429: un proxy o un balanceador puede mandar
  // Retry-After con un 503, y al cliente le sirve igual.
  const retryAfterSeconds = parseRetryAfter(response.headers.get("Retry-After"));
  // El backend lo devuelve en TODA respuesta (HU-1.12); puede faltar si el
  // error lo generó un proxy que nunca llegó a la app.
  const requestId = response.headers.get(REQUEST_ID_HEADER);
  if (isApiErrorResponse(body)) {
    const { code, message, details, error_id: errorId } = body.error;
    return new ApiError(message, {
      url,
      status: response.status,
      code,
      details,
      errorId,
      retryAfterSeconds,
      requestId,
    });
  }
  return new ApiError(`HTTP ${response.status} en ${url}`, {
    url,
    status: response.status,
    retryAfterSeconds,
    requestId,
  });
}

/** Cliente de la API de Rover. Un método tipado por endpoint. */
export class ApiClient {
  readonly baseUrl: string;

  constructor(config: ApiClientConfig = {}) {
    this.baseUrl = resolveBaseUrl(config.baseUrl);
  }

  /** GET /v1/health — estado, versión y entorno del backend. */
  async getHealth(): Promise<HealthResponse> {
    const url = `${this.baseUrl}/v1/health`;
    const { status, data } = await getJson(url);
    if (!isHealthResponse(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * GET /v1/health/db — conectividad del backend con la base de datos.
   * Si la base está caída, el backend responde 503 y esto lanza ApiError
   * (status 503), igual que cualquier otro no-2xx.
   */
  async getDbHealth(): Promise<DbHealthResponse> {
    const url = `${this.baseUrl}/v1/health/db`;
    const { status, data } = await getJson(url);
    if (!isDbHealthResponse(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * POST /v1/auth/register — registra un usuario (delegado en Supabase Auth)
   * y devuelve su sesión (access + refresh token). El backend no firma JWT
   * propios. Un email ya existente responde 409; email inválido o contraseña
   * débil, 422; fallo del proveedor, 502/503 — en los tres casos esto lanza
   * ApiError con el status correspondiente (mismo contrato que getHealth).
   */
  async register(payload: RegisterRequest): Promise<RegisterResponse> {
    const url = `${this.baseUrl}/v1/auth/register`;
    const { status, data } = await postJson(url, payload);
    if (!isRegisterResponse(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * POST /v1/auth/login — inicia sesión (delegado en Supabase Auth) y devuelve
   * usuario + sesión (access + refresh token). Credenciales inválidas → 401;
   * email sin confirmar → 403; rate limit → 429; fallo del proveedor → 503.
   * En todos esos casos esto lanza ApiError con el status correspondiente.
   */
  async login(payload: LoginRequest): Promise<LoginResponse> {
    const url = `${this.baseUrl}/v1/auth/login`;
    const { status, data } = await postJson(url, payload);
    if (!isLoginResponse(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * GET /v1/users/me — perfil completo del usuario (id, email, plan,
   * preferences, timestamps). Requiere el access token en Authorization; sin
   * él o con token inválido responde 401 y esto lanza ApiError.
   *
   * Es también el "¿quién soy?" del cliente: desde la HU-1.9 no hay un
   * endpoint aparte de identidad (`/v1/auth/me` se consolidó aquí), porque
   * costaba lo mismo y devolvía un subconjunto de esto.
   */
  async getProfile(accessToken: string): Promise<Profile> {
    const url = `${this.baseUrl}/v1/users/me`;
    const { status, data } = await getJson(url, { Authorization: `Bearer ${accessToken}` });
    if (!isProfile(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * PATCH /v1/users/me — actualiza SOLO `preferences` (merge superficial en el
   * backend) y devuelve el perfil. El tipo `ProfileUpdate` impide enviar
   * `plan`/`email`/`id`; el backend responde 422 si aun así llegan.
   */
  async updateProfile(accessToken: string, update: ProfileUpdate): Promise<Profile> {
    const url = `${this.baseUrl}/v1/users/me`;
    const { status, data } = await patchJson(url, update, {
      Authorization: `Bearer ${accessToken}`,
    });
    if (!isProfile(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * POST /v1/chat — conversa con Rover y **entrega la respuesta trozo a trozo**.
   *
   * Se usa como un `for await`, y cada vuelta es un evento ya tipado:
   *
   * ```ts
   * let texto = "";
   * for await (const evento of client.streamChat(token, { message: "hola" })) {
   *   if (evento.type === "start") conversationId = evento.conversation_id;
   *   else if (evento.type === "delta") texto += evento.text;   // pintar aquí
   *   else if (evento.type === "error") mostrarError(evento.error.message);
   * }
   * ```
   *
   * **Los dos sitios por los que puede fallar, y no son el mismo:**
   *
   * - *Antes* de que empiece la respuesta (sin token, cuota agotada,
   *   conversación ajena, el modelo caído) el backend responde con un status
   *   HTTP normal, así que esto **lanza `ApiError`** como cualquier otro método
   *   del cliente — con su `code`, su `retryAfterSeconds` y su `requestId`.
   * - *A mitad* del stream ya no hay status que cambiar: llega un evento
   *   `{ type: "error" }` con el mismo cuerpo, y el bucle termina después de
   *   él. No se lanza, porque para entonces puede haber texto en pantalla que
   *   el usuario está leyendo y tirar una excepción lo borraría.
   *
   * Abandonar el `for await` (un `break`, o desmontar la vista) cancela la
   * lectura y suelta la conexión: el backend lo detecta, cierra su lado y
   * **descarta la respuesta a medias** — la conversación queda con la pregunta
   * y sin respuesta, nunca con media respuesta.
   *
   * `signal` permite cancelar desde fuera (un botón de "parar"), con la misma
   * consecuencia.
   */
  async *streamChat(
    accessToken: string,
    request: ChatRequest,
    options: { signal?: AbortSignal } = {},
  ): AsyncGenerator<ChatStreamEvent, void, undefined> {
    const url = `${this.baseUrl}/v1/chat`;
    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // SSE, no JSON: es lo que se va a recibir y lo que un proxy debe
          // ver para no intentar transformarlo.
          Accept: "text/event-stream",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify(request),
        // ``?? null`` y no ``options.signal``: con ``exactOptionalPropertyTypes``
        // el `undefined` explícito no encaja donde el DOM declara `| null`.
        signal: options.signal ?? null,
      });
    } catch (cause) {
      throw new ApiError(`Fallo de red llamando a ${url}`, { url, status: null, cause });
    }

    if (!response.ok) {
      throw await toApiError(url, response);
    }
    if (response.body === null) {
      throw new ApiError(`Respuesta de ${url} sin cuerpo`, { url, status: response.status });
    }

    for await (const data of readSseFrames(response.body)) {
      const evento = parseChatStreamEvent(data);
      // Un marco ilegible o de un tipo desconocido se descarta y el stream
      // sigue: misma política que el backend con los eventos rotos del
      // proveedor. Una respuesta a medias en pantalla vale más que un corte.
      if (evento !== null) {
        yield evento;
      }
    }
  }

  /**
   * GET /v1/chat/sessions — las conversaciones **vivas** del usuario, de la más
   * activa a la más vieja (cada mensaje toca su conversación, HU-2.5).
   *
   * Solo cabeceras: id, título y timestamps. El historial se pide conversación
   * por conversación con `getChatSession`, para que pintar una barra lateral no
   * signifique descargar toda la cuenta.
   *
   * Las borradas no aparecen. `limit` acota (1–100, por defecto 50); si
   * `items.length === limit` puede haber más.
   */
  async listChatSessions(
    accessToken: string,
    options: { limit?: number } = {},
  ): Promise<ChatSessionList> {
    const query = options.limit === undefined ? "" : `?limit=${String(options.limit)}`;
    const url = `${this.baseUrl}/v1/chat/sessions${query}`;
    const { status, data } = await getJson(url, { Authorization: `Bearer ${accessToken}` });
    if (!isChatSessionList(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * GET /v1/chat/sessions/{id} — una conversación con su historial en orden.
   *
   * Solo texto conversacional: los pasos internos de tool-calling se guardan
   * pero no se exponen, y `ChatSessionMessage` ni siquiera los declara.
   *
   * Si la conversación no existe, está borrada o **es de otra persona**, el
   * backend responde 404 en los tres casos y esto lanza `ApiError` con
   * `code === "not_found"`. Es deliberado que no se distingan: un 403 para la
   * ajena confirmaría que ese id existe.
   */
  async getChatSession(accessToken: string, sessionId: string): Promise<ChatSession> {
    const url = `${this.baseUrl}/v1/chat/sessions/${encodeURIComponent(sessionId)}`;
    const { status, data } = await getJson(url, { Authorization: `Bearer ${accessToken}` });
    if (!isChatSession(data)) {
      throw new ApiError(`Respuesta de ${url} con forma inesperada`, { url, status });
    }
    return data;
  }

  /**
   * DELETE /v1/chat/sessions/{id} — borra una conversación (**soft-delete**).
   *
   * Deja de aparecer en la lista, deja de ser accesible y `streamChat` con ese
   * id responde 404. Los mensajes siguen en la base: es lo que permite un
   * purgado por retención con fecha y una recuperación por soporte.
   *
   * **Borrar dos veces lanza `ApiError` la segunda** (404), no vuelve a
   * responder 204: un 204 sobre una ya borrada diría "ese id existió y era
   * tuyo", que es justo lo que el 404 uniforme evita. Para el cliente el
   * desenlace es el mismo, así que conviene tratar el `not_found` de un borrado
   * como "ya no está" y no como un fallo que mostrar.
   */
  async deleteChatSession(accessToken: string, sessionId: string): Promise<void> {
    const url = `${this.baseUrl}/v1/chat/sessions/${encodeURIComponent(sessionId)}`;
    let response: Response;
    try {
      response = await fetch(url, {
        method: "DELETE",
        headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
      });
    } catch (cause) {
      throw new ApiError(`Fallo de red llamando a ${url}`, { url, status: null, cause });
    }
    if (!response.ok) {
      throw await toApiError(url, response);
    }
    // 204 sin cuerpo: no hay nada que parsear ni que devolver.
  }
}

/** GET de un JSON con errores normalizados a ApiError. Devuelve el cuerpo SIN tipar. */
async function getJson(
  url: string,
  headers: Record<string, string> = {},
): Promise<{ status: number; data: unknown }> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json", ...headers } });
  } catch (cause) {
    throw new ApiError(`Fallo de red llamando a ${url}`, { url, status: null, cause });
  }

  if (!response.ok) {
    throw await toApiError(url, response);
  }

  let data: unknown;
  try {
    data = (await response.json()) as unknown;
  } catch (cause) {
    throw new ApiError(`Cuerpo no-JSON en ${url}`, { url, status: response.status, cause });
  }
  return { status: response.status, data };
}

/** Envía un cuerpo JSON con el método dado; errores normalizados a ApiError. */
async function sendJson(
  method: "POST" | "PATCH",
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<{ status: number; data: unknown }> {
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", Accept: "application/json", ...headers },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError(`Fallo de red llamando a ${url}`, { url, status: null, cause });
  }

  if (!response.ok) {
    throw await toApiError(url, response);
  }

  let data: unknown;
  try {
    data = (await response.json()) as unknown;
  } catch (cause) {
    throw new ApiError(`Cuerpo no-JSON en ${url}`, { url, status: response.status, cause });
  }
  return { status: response.status, data };
}

/** POST de un JSON. Devuelve el cuerpo SIN tipar. */
function postJson(url: string, body: unknown): Promise<{ status: number; data: unknown }> {
  return sendJson("POST", url, body);
}

/** PATCH de un JSON (con headers, p. ej. Authorization). Devuelve el cuerpo SIN tipar. */
function patchJson(
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<{ status: number; data: unknown }> {
  return sendJson("PATCH", url, body, headers);
}
