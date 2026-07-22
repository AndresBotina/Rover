/**
 * Tipos del recurso health (GET /v1/health).
 *
 * Definidos A MANO por ahora, espejo del modelo Pydantic del backend
 * (apps/backend/app/api/v1/health.py). El plan (Épica 1, cuando existan los
 * endpoints de auth) es generar este directorio desde el esquema OpenAPI del
 * backend; por eso los tipos viven separados del cliente.
 */

/** Respuesta de GET /v1/health. */
export interface HealthResponse {
  status: "ok";
  version: string;
  env: string;
}

/** Type guard: valida en runtime que un JSON desconocido es un HealthResponse. */
export function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return v["status"] === "ok" && typeof v["version"] === "string" && typeof v["env"] === "string";
}

/**
 * Respuesta de GET /v1/health/db cuando la base responde.
 *
 * Solo describe el caso SANO: si la base está caída, el backend devuelve 503
 * con el formato único de error (HU-1.8), no un cuerpo propio con
 * `status: "error"`. Así todos los fallos de la API se parsean igual.
 */
export interface DbHealthResponse {
  status: "ok";
}

/** Type guard: valida en runtime que un JSON desconocido es un DbHealthResponse. */
export function isDbHealthResponse(value: unknown): value is DbHealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  return (value as Record<string, unknown>)["status"] === "ok";
}
