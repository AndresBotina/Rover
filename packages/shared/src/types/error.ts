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

/**
 * Código del 429. Se exporta como constante porque es el único que el cliente
 * necesita nombrar para decidir *reintentar*, en vez de solo mostrar el error.
 *
 * Es el mismo tanto si el límite lo puso la API (HU-1.7) como si viene de un
 * rechazo del proveedor de identidad: para quien llama la acción es idéntica
 * —esperar y reintentar— y el `code` describe el dominio, no de dónde salió.
 */
export const RATE_LIMITED: KnownApiErrorCode = "rate_limited";

/**
 * Segundos a esperar según la cabecera `Retry-After`, o `null` si no la hay o
 * no se entiende.
 *
 * RFC 9110 permite dos formas y aquí se aceptan las dos: un número de segundos
 * (lo que manda esta API) o una fecha HTTP (lo que podría interponer un proxy o
 * un balanceador). Nunca devuelve un valor negativo: una fecha ya pasada
 * significa "reintenta ya", no "reintenta en el pasado".
 */
export function parseRetryAfter(
  value: string | null | undefined,
  now: Date = new Date(),
): number | null {
  if (typeof value !== "string") {
    return null;
  }
  const raw = value.trim();
  if (raw === "") {
    return null;
  }

  // Forma 1: delta-seconds. Solo dígitos, para no aceptar "12abc" ni "1e3".
  if (/^\d+$/.test(raw)) {
    return Number(raw);
  }

  // Un valor que PARECE un número pero no encajó arriba ("-5", "1.5") está mal
  // escrito, no es una fecha: se descarta aquí porque `Date.parse` interpreta
  // algunos de esos como años y devolvería un valor sin sentido.
  if (/^[+-]?[\d.]+$/.test(raw)) {
    return null;
  }

  // Forma 2: fecha HTTP.
  const target = Date.parse(raw);
  if (Number.isNaN(target)) {
    return null;
  }
  return Math.max(0, Math.ceil((target - now.getTime()) / 1000));
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
