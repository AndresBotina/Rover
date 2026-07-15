/**
 * Cableado de @rover/shared (HU-0.7): confirma que mobile resuelve el paquete
 * del workspace y que sus tipos pasan el tsc estricto. La app real llega en
 * HU-4.1, donde este helper se usará con EXPO_PUBLIC_API_URL como baseUrl.
 */

import { ApiClient, type HealthResponse } from "@rover/shared";

/** Consulta el healthcheck del backend. */
export function fetchBackendHealth(baseUrl?: string): Promise<HealthResponse> {
  return new ApiClient({ baseUrl }).getHealth();
}
