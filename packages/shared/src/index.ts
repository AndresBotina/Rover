// API pública de @rover/shared: marca, tipos compartidos y cliente HTTP tipado.
// web y mobile importan SOLO desde aquí; los internos pueden reorganizarse.

export { APP_NAME } from "./config.ts";

export {
  isLoginResponse,
  isRegisterResponse,
  type AuthSession,
  type AuthUser,
  type LoginRequest,
  type LoginResponse,
  type Plan,
  type RegisterActive,
  type RegisterPendingConfirmation,
  type RegisterRequest,
  type RegisterResponse,
} from "./types/auth.ts";

export { isProfile, type Profile, type ProfileUpdate } from "./types/profile.ts";

export {
  isChatDeltaEvent,
  isChatDoneEvent,
  isChatErrorEvent,
  isChatStartEvent,
  isChatStreamEvent,
  parseChatStreamEvent,
  readSseFrames,
  type ChatDeltaEvent,
  type ChatDoneEvent,
  type ChatErrorEvent,
  type ChatRequest,
  type ChatStartEvent,
  type ChatStreamEvent,
} from "./types/chat.ts";

export {
  isApiErrorResponse,
  parseRetryAfter,
  RATE_LIMITED,
  REQUEST_ID_HEADER,
  type ApiErrorBody,
  type ApiErrorCode,
  type ApiErrorResponse,
  type KnownApiErrorCode,
} from "./types/error.ts";

export {
  isDbHealthResponse,
  isHealthResponse,
  type DbHealthResponse,
  type HealthResponse,
} from "./types/health.ts";

export { ApiClient, ApiError, isRateLimitedError } from "./client/client.ts";
export { DEFAULT_BASE_URL, resolveBaseUrl, type ApiClientConfig } from "./client/config.ts";
