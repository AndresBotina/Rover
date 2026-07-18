/**
 * Cliente HTTP tipado del backend de Rover.
 *
 * Usa fetch NATIVO (Node ≥ 18, Next.js y React Native lo traen) para no atar
 * el paquete a una librería HTTP. Escrito a mano por ahora: en Épica 1 la idea
 * es generarlo desde el esquema OpenAPI del backend, por eso los tipos viven
 * aparte en ../types y aquí solo hay transporte + validación.
 */

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
 */
export class ApiError extends Error {
  /** URL que se estaba llamando. */
  readonly url: string;
  /** Status HTTP de la respuesta, o null si la petición no llegó (fallo de red). */
  readonly status: number | null;

  constructor(message: string, options: { url: string; status: number | null; cause?: unknown }) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.url = options.url;
    this.status = options.status;
  }
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
}

/** GET de un JSON con errores normalizados a ApiError. Devuelve el cuerpo SIN tipar. */
async function getJson(url: string): Promise<{ status: number; data: unknown }> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" } });
  } catch (cause) {
    throw new ApiError(`Fallo de red llamando a ${url}`, { url, status: null, cause });
  }

  if (!response.ok) {
    throw new ApiError(`HTTP ${response.status} en ${url}`, { url, status: response.status });
  }

  let data: unknown;
  try {
    data = (await response.json()) as unknown;
  } catch (cause) {
    throw new ApiError(`Cuerpo no-JSON en ${url}`, { url, status: response.status, cause });
  }
  return { status: response.status, data };
}
