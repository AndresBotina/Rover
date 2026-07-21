/**
 * Tests del cliente con fetch mockeado (node:test nativo, sin deps extra).
 * Node ≥ 22.18 ejecuta .ts directo (type stripping); por eso los imports
 * relativos llevan extensión .ts (allowImportingTsExtensions en tsconfig).
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiClient, ApiError } from "./client.ts";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("getHealth parsea y tipa la respuesta, llamando a ${baseUrl}/v1/health", async () => {
  let calledUrl: string | undefined;
  globalThis.fetch = async (input) => {
    calledUrl = String(input);
    return jsonResponse({ status: "ok", version: "0.1.0", env: "local" });
  };

  // La barra final de la baseUrl se normaliza.
  const health = await new ApiClient({ baseUrl: "http://api.test/" }).getHealth();

  assert.equal(calledUrl, "http://api.test/v1/health");
  assert.deepEqual(health, { status: "ok", version: "0.1.0", env: "local" });
});

test("getHealth usa el default local si no se pasa baseUrl", async () => {
  let calledUrl: string | undefined;
  globalThis.fetch = async (input) => {
    calledUrl = String(input);
    return jsonResponse({ status: "ok", version: "0.1.0", env: "local" });
  };

  await new ApiClient().getHealth();

  assert.equal(calledUrl, "http://localhost:8000/v1/health");
});

test("getDbHealth parsea la respuesta de /v1/health/db", async () => {
  let calledUrl: string | undefined;
  globalThis.fetch = async (input) => {
    calledUrl = String(input);
    return jsonResponse({ status: "ok", detail: null });
  };

  const dbHealth = await new ApiClient({ baseUrl: "http://api.test" }).getDbHealth();

  assert.equal(calledUrl, "http://api.test/v1/health/db");
  assert.deepEqual(dbHealth, { status: "ok", detail: null });
});

test("un status no-2xx lanza ApiError con el status", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "boom" }, 500);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getHealth(),
    (error: unknown) => error instanceof ApiError && error.status === 500,
  );
});

test("un cuerpo con forma inesperada lanza ApiError (no devuelve algo mal tipado)", async () => {
  globalThis.fetch = async () => jsonResponse({ status: "weird" });

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getHealth(),
    (error: unknown) => error instanceof ApiError && error.status === 200,
  );
});

test("register (con sesión) hace POST a /v1/auth/register y parsea la respuesta active", async () => {
  let calledUrl: string | undefined;
  let calledInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    calledUrl = String(input);
    calledInit = init;
    return jsonResponse(
      {
        status: "active",
        user: { id: "11111111-1111-1111-1111-111111111111", email: "a@b.com" },
        session: { access_token: "at", refresh_token: "rt", token_type: "bearer" },
      },
      201,
    );
  };

  const result = await new ApiClient({ baseUrl: "http://api.test" }).register({
    email: "a@b.com",
    password: "una-contrasena-larga",
  });

  assert.equal(calledUrl, "http://api.test/v1/auth/register");
  assert.equal(calledInit?.method, "POST");
  assert.deepEqual(JSON.parse(String(calledInit?.body)), {
    email: "a@b.com",
    password: "una-contrasena-larga",
  });
  assert.equal(result.status, "active");
  // El discriminante permite estrechar sin castings: en 'active' hay sesión.
  assert.equal(result.status === "active" ? result.session.access_token : null, "at");
});

test("register (confirmación pendiente) devuelve la variante sin sesión", async () => {
  globalThis.fetch = async () =>
    jsonResponse(
      {
        status: "pending_email_confirmation",
        user: { id: "11111111-1111-1111-1111-111111111111", email: "a@b.com" },
        session: null,
      },
      201,
    );

  const result = await new ApiClient({ baseUrl: "http://api.test" }).register({
    email: "a@b.com",
    password: "una-contrasena-larga",
  });

  assert.equal(result.status, "pending_email_confirmation");
  assert.equal(result.session, null);
});

test("login hace POST a /v1/auth/login y parsea usuario + sesión", async () => {
  let calledUrl: string | undefined;
  let calledInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    calledUrl = String(input);
    calledInit = init;
    return jsonResponse(
      {
        user: { id: "11111111-1111-1111-1111-111111111111", email: "a@b.com" },
        session: { access_token: "at", refresh_token: "rt", token_type: "bearer" },
      },
      200,
    );
  };

  const result = await new ApiClient({ baseUrl: "http://api.test" }).login({
    email: "a@b.com",
    password: "una-contrasena-larga",
  });

  assert.equal(calledUrl, "http://api.test/v1/auth/login");
  assert.equal(calledInit?.method, "POST");
  assert.equal(result.session.access_token, "at");
  assert.equal(result.user.id, "11111111-1111-1111-1111-111111111111");
});

test("login con credenciales inválidas (401) lanza ApiError con ese status", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "Email o contraseña incorrectos." }, 401);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).login({
      email: "a@b.com",
      password: "una-contrasena-larga",
    }),
    (error: unknown) => error instanceof ApiError && error.status === 401,
  );
});

test("login con email sin confirmar (403) lanza ApiError con status 403", async () => {
  globalThis.fetch = async () =>
    jsonResponse({ detail: { reason: "email_not_confirmed", message: "…" } }, 403);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).login({
      email: "a@b.com",
      password: "una-contrasena-larga",
    }),
    (error: unknown) => error instanceof ApiError && error.status === 403,
  );
});

test("getMe envía el token en Authorization y parsea la identidad", async () => {
  let calledUrl: string | undefined;
  let calledHeaders: Headers | undefined;
  globalThis.fetch = async (input, init) => {
    calledUrl = String(input);
    calledHeaders = new Headers(init?.headers);
    return jsonResponse(
      { id: "11111111-1111-1111-1111-111111111111", email: "a@b.com", plan: "free" },
      200,
    );
  };

  const me = await new ApiClient({ baseUrl: "http://api.test" }).getMe("mi-access-token");

  assert.equal(calledUrl, "http://api.test/v1/auth/me");
  assert.equal(calledHeaders?.get("Authorization"), "Bearer mi-access-token");
  assert.deepEqual(me, {
    id: "11111111-1111-1111-1111-111111111111",
    email: "a@b.com",
    plan: "free",
  });
});

test("getMe con token inválido (401) lanza ApiError con status 401", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "No autenticado." }, 401);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getMe("token-malo"),
    (error: unknown) => error instanceof ApiError && error.status === 401,
  );
});

const PROFILE = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "a@b.com",
  plan: "free",
  preferences: { idioma: "es" },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

test("getProfile envía el token y parsea el perfil completo", async () => {
  let calledUrl: string | undefined;
  let calledHeaders: Headers | undefined;
  globalThis.fetch = async (input, init) => {
    calledUrl = String(input);
    calledHeaders = new Headers(init?.headers);
    return jsonResponse(PROFILE, 200);
  };

  const profile = await new ApiClient({ baseUrl: "http://api.test" }).getProfile("tok");

  assert.equal(calledUrl, "http://api.test/v1/users/me");
  assert.equal(calledHeaders?.get("Authorization"), "Bearer tok");
  assert.deepEqual(profile, PROFILE);
});

test("updateProfile hace PATCH con el token y el cuerpo, y parsea el perfil", async () => {
  let calledUrl: string | undefined;
  let calledInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    calledUrl = String(input);
    calledInit = init;
    return jsonResponse({ ...PROFILE, preferences: { idioma: "en" } }, 200);
  };

  const profile = await new ApiClient({ baseUrl: "http://api.test" }).updateProfile("tok", {
    preferences: { idioma: "en" },
  });

  assert.equal(calledUrl, "http://api.test/v1/users/me");
  assert.equal(calledInit?.method, "PATCH");
  assert.equal(new Headers(calledInit?.headers).get("Authorization"), "Bearer tok");
  assert.deepEqual(JSON.parse(String(calledInit?.body)), { preferences: { idioma: "en" } });
  assert.deepEqual(profile.preferences, { idioma: "en" });
});

test("getProfile con perfil de forma inesperada lanza ApiError", async () => {
  globalThis.fetch = async () => jsonResponse({ id: "x" }, 200);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getProfile("tok"),
    (error: unknown) => error instanceof ApiError && error.status === 200,
  );
});

test("register con email duplicado (409) lanza ApiError con ese status", async () => {
  globalThis.fetch = async () =>
    jsonResponse({ detail: "Ya existe una cuenta con ese email." }, 409);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).register({
      email: "a@b.com",
      password: "una-contrasena-larga",
    }),
    (error: unknown) => error instanceof ApiError && error.status === 409,
  );
});

test("register con forma de respuesta inesperada lanza ApiError", async () => {
  globalThis.fetch = async () => jsonResponse({ user: { id: "x" } }, 201);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).register({
      email: "a@b.com",
      password: "una-contrasena-larga",
    }),
    (error: unknown) => error instanceof ApiError && error.status === 201,
  );
});

test("un fallo de red lanza ApiError con status null", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getHealth(),
    (error: unknown) => error instanceof ApiError && error.status === null,
  );
});
