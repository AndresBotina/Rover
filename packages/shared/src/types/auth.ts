/**
 * Tipos del recurso auth (POST /v1/auth/register).
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

/** Respuesta de éxito (201) de POST /v1/auth/register. */
export interface RegisterResponse {
  user: AuthUser;
  session: AuthSession;
}

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

/** Type guard: valida en runtime que un JSON desconocido es un RegisterResponse. */
export function isRegisterResponse(value: unknown): value is RegisterResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return isAuthUser(v["user"]) && isAuthSession(v["session"]);
}
