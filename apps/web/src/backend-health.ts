/**
 * Cableado de @rover/shared (HU-0.7): confirma que web resuelve el paquete del
 * workspace y que sus tipos pasan el tsc estricto. La UI real llega en HU-3.1,
 * donde este helper se usará con NEXT_PUBLIC_API_URL como baseUrl.
 */

import { ApiClient, type HealthResponse } from "@rover/shared";

/** Consulta el healthcheck del backend. */
export function fetchBackendHealth(baseUrl?: string): Promise<HealthResponse> {
  return new ApiClient({ baseUrl }).getHealth();
}
