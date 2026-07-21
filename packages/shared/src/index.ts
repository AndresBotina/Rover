// API pública de @rover/shared: marca, tipos compartidos y cliente HTTP tipado.
// web y mobile importan SOLO desde aquí; los internos pueden reorganizarse.

export { APP_NAME } from "./config.ts";

export {
  isRegisterResponse,
  type AuthSession,
  type AuthUser,
  type RegisterRequest,
  type RegisterResponse,
} from "./types/auth.ts";

export {
  isDbHealthResponse,
  isHealthResponse,
  type DbHealthResponse,
  type HealthResponse,
} from "./types/health.ts";

export { ApiClient, ApiError } from "./client/client.ts";
export { DEFAULT_BASE_URL, resolveBaseUrl, type ApiClientConfig } from "./client/config.ts";
