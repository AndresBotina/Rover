/**
 * Configuración del cliente HTTP.
 *
 * La base URL NO va hardcodeada: cada app la inyecta al crear el cliente,
 * típicamente desde su variable de entorno pública (NEXT_PUBLIC_API_URL en
 * web, EXPO_PUBLIC_API_URL en mobile). Sin valor explícito se usa el default
 * del backend local.
 */

/** Base URL por defecto: backend local (uvicorn / docker compose en el 8000). */
export const DEFAULT_BASE_URL = "http://localhost:8000";

/** Opciones de construcción del cliente. */
export interface ApiClientConfig {
  /** Base URL del backend, sin path (ej. https://rover-backend.onrender.com). */
  baseUrl?: string | undefined;
}

/** Resuelve la base URL efectiva: la explícita (o el default local) sin barra final. */
export function resolveBaseUrl(baseUrl?: string): string {
  return (baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
}
