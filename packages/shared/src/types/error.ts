/**
 * Formato ÚNICO de error de la API (espejo de apps/backend/app/core/errors.py).
 *
 * CUALQUIER respuesta no-2xx del backend —de un endpoint, de la validación o
 * de un fallo inesperado— tiene esta forma, así que web y móvil la parsean una
 * sola vez con `isApiErrorResponse`.
 */

/**
 * Códigos que el backend puede devolver HOY. El tipo admite además cualquier
 * `string`: un cliente ya publicado tiene que poder parsear un error con un
 * código que aún no conocía (el backend evoluciona antes que las apps). La
 * unión conocida sigue dando autocompletado y protege los `switch`.
 */
export type KnownApiErrorCode =
  | "unauthenticated"
  | "invalid_credentials"
  | "email_not_confirmed"
  | "forbidden"
  | "not_found"
  | "method_not_allowed"
  | "email_already_exists"
  | "conflict"
  | "validation_error"
  | "weak_password"
  | "invalid_email"
  | "preferences_too_large"
  | "rate_limited"
  | "service_unavailable"
  | "internal_error"
  | "http_error";

 
export type ApiErrorCode = KnownApiErrorCode | (string & {});

/** Contenido del error. */
export interface ApiErrorBody {
  /** Código estable, legible por máquina: por AQUÍ se ramifica, no por el status. */
  code: ApiErrorCode;
  /** Mensaje seguro de mostrar al usuario. */
  message: string;
  /** Estructura opcional; en un 422 trae `errors` (los fallos campo a campo). */
  details: Record<string, unknown> | null;
  /** Identificador para reportar un 500; `null` en el resto de errores. */
  error_id: string | null;
}

/** Cuerpo completo de una respuesta de error. */
export interface ApiErrorResponse {
  error: ApiErrorBody;
}

/** Type guard: valida en runtime que un JSON desconocido es un error de la API. */
export function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const error = (value as Record<string, unknown>)["error"];
  if (typeof error !== "object" || error === null) {
    return false;
  }
  const e = error as Record<string, unknown>;
  const details = e["details"];
  return (
    typeof e["code"] === "string" &&
    typeof e["message"] === "string" &&
    (details === null || (typeof details === "object" && !Array.isArray(details))) &&
    (e["error_id"] === null || typeof e["error_id"] === "string")
  );
}
