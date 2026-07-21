/**
 * Tipos del perfil de usuario (GET/PATCH /v1/users/me).
 *
 * Espejo de los modelos Pydantic del backend (apps/backend/app/api/v1/users.py).
 */

import type { Plan } from "./auth.ts";

/** Perfil completo del usuario autenticado. */
export interface Profile {
  id: string;
  email: string;
  plan: Plan;
  preferences: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * Cuerpo del PATCH /v1/users/me: SOLO `preferences` es editable.
 *
 * A nivel de tipos es imposible enviar `plan`, `email` o `id`: este tipo no los
 * declara, y el chequeo de propiedades excedentes de TypeScript rechaza un
 * literal que los incluya. El backend además responde 422 ante campos
 * desconocidos (defensa en profundidad).
 */
export interface ProfileUpdate {
  preferences: Record<string, unknown>;
}

/** Type guard: valida en runtime que un JSON desconocido es un Profile. */
export function isProfile(value: unknown): value is Profile {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  const preferences = v["preferences"];
  return (
    typeof v["id"] === "string" &&
    typeof v["email"] === "string" &&
    (v["plan"] === "free" || v["plan"] === "pro") &&
    typeof preferences === "object" &&
    preferences !== null &&
    !Array.isArray(preferences) &&
    typeof v["created_at"] === "string" &&
    typeof v["updated_at"] === "string"
  );
}
