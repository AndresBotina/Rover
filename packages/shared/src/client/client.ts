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
import { isApiErrorResponse, type ApiErrorCode } from "../types/error.ts";
import { isProfile, type Profile, type ProfileUpdate } from "../types/profile.ts";
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

  constructor(
    message: string,
    options: {
      url: string;
      status: number | null;
      code?: ApiErrorCode | null;
      details?: Record<string, unknown> | null;
      errorId?: string | null;
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
  }
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
  if (isApiErrorResponse(body)) {
    const { code, message, details, error_id: errorId } = body.error;
    return new ApiError(message, { url, status: response.status, code, details, errorId });
  }
  return new ApiError(`HTTP ${response.status} en ${url}`, { url, status: response.status });
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
