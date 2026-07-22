/**
 * Tipos del recurso auth (POST /v1/auth/register y /v1/auth/login).
 *
 * Definidos A MANO por ahora, espejo de los modelos Pydantic del backend
 * (apps/backend/app/api/v1/auth.py) — mismos nombres de campo, sin inventar
 * un mapeo camelCase que el backend no tiene. El backend delega la identidad
 * en Supabase Auth: NO firma JWT propios, la sesión que trae la respuesta es
 * la de Supabase (access + refresh token).
 */

/** Cuerpo de POST /v1/auth/register. */
export interface RegisterRequest {
  email: string;
  password: string;
}

/** Cuerpo de POST /v1/auth/login. */
export interface LoginRequest {
  email: string;
  password: string;
}

/** Datos mínimos del usuario. Nunca incluye la contraseña. */
export interface AuthUser {
  id: string;
  email: string;
}

/** Sesión de Supabase devuelta tras un alta (o, más adelante, un login). */
export interface AuthSession {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

/**
 * Registro con sesión: la confirmación de email está desactivada, el usuario
 * ya puede operar. El cliente inicia sesión directamente.
 */
export interface RegisterActive {
  status: "active";
  user: AuthUser;
  session: AuthSession;
}

/**
 * Registro con confirmación de email PENDIENTE: el usuario se creó pero aún no
 * hay sesión. El cliente debe mostrar "revisa tu correo".
 */
export interface RegisterPendingConfirmation {
  status: "pending_email_confirmation";
  user: AuthUser;
  session: null;
}

/**
 * Respuesta de éxito (201) de POST /v1/auth/register.
 *
 * Unión DISCRIMINADA por `status`: el cliente hace `if (res.status ===
 * "active")` y TypeScript estrecha el tipo (sesión presente) sin castings; en
 * el otro caso, no hay sesión. Nunca se distingue mirando si `session` es
 * nula: el discriminante es `status`.
 */
export type RegisterResponse = RegisterActive | RegisterPendingConfirmation;

function isAuthUser(value: unknown): value is AuthUser {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return typeof v["id"] === "string" && typeof v["email"] === "string";
}

function isAuthSession(value: unknown): value is AuthSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return (
    typeof v["access_token"] === "string" &&
    typeof v["refresh_token"] === "string" &&
    typeof v["token_type"] === "string"
  );
}

/**
 * Type guard: valida en runtime que un JSON desconocido es un RegisterResponse,
 * cubriendo AMBAS formas de la unión: `active` exige una sesión válida;
 * `pending_email_confirmation` exige que NO haya sesión (null o ausente).
 */
export function isRegisterResponse(value: unknown): value is RegisterResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  if (!isAuthUser(v["user"])) {
    return false;
  }
  if (v["status"] === "active") {
    return isAuthSession(v["session"]);
  }
  if (v["status"] === "pending_email_confirmation") {
    return v["session"] === null || v["session"] === undefined;
  }
  return false;
}

/**
 * Respuesta de éxito (200) de POST /v1/auth/login. A diferencia del registro,
 * el login SIEMPRE abre sesión, así que no es una unión: usuario + sesión.
 *
 * Nota sobre errores: credenciales inválidas → 401; email sin confirmar → 403
 * con `{ detail: { reason: "email_not_confirmed", message } }`; rate limit →
 * 429; fallo del proveedor → 503. El cliente los recibe como `ApiError` con su
 * `status` (el 403 se distingue por el status, sin inferir).
 */
export interface LoginResponse {
  user: AuthUser;
  session: AuthSession;
}

/** Type guard: valida en runtime que un JSON desconocido es un LoginResponse. */
export function isLoginResponse(value: unknown): value is LoginResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return isAuthUser(v["user"]) && isAuthSession(v["session"]);
}

/** Plan del usuario (espejo del StrEnum del backend). */
export type Plan = "free" | "pro";

// NOTA (HU-1.9): aquí vivían `MeResponse` e `isMeResponse`, el tipo de
// GET /v1/auth/me. Ese endpoint se consolidó en GET /v1/users/me, cuyo tipo
// `Profile` (types/profile.ts) es un superconjunto: quien solo quiera la
// identidad usa `getProfile()` y lee id/email/plan.
