/**
 * Tests del cliente con fetch mockeado (node:test nativo, sin deps extra).
 * Node ≥ 22.18 ejecuta .ts directo (type stripping); por eso los imports
 * relativos llevan extensión .ts (allowImportingTsExtensions en tsconfig).
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { REQUEST_ID_HEADER } from "../types/error.ts";
import { ApiClient, ApiError, isRateLimitedError } from "./client.ts";

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
    return jsonResponse({ status: "ok" });
  };

  const dbHealth = await new ApiClient({ baseUrl: "http://api.test" }).getDbHealth();

  assert.equal(calledUrl, "http://api.test/v1/health/db");
  assert.deepEqual(dbHealth, { status: "ok" });
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

test("login con credenciales inválidas (401) lanza ApiError con código y mensaje", async () => {
  globalThis.fetch = async () =>
    jsonResponse(
      {
        error: {
          code: "invalid_credentials",
          message: "Email o contraseña incorrectos.",
          details: null,
          error_id: null,
        },
      },
      401,
    );

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).login({
      email: "a@b.com",
      password: "una-contrasena-larga",
    }),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 401 &&
      error.code === "invalid_credentials" &&
      // El mensaje del servidor se conserva: es seguro de mostrar.
      error.message === "Email o contraseña incorrectos.",
  );
});

test("login con email sin confirmar se distingue por el code, no por el status", async () => {
  globalThis.fetch = async () =>
    jsonResponse(
      {
        error: {
          code: "email_not_confirmed",
          message: "Debes confirmar tu correo antes de iniciar sesión.",
          details: null,
          error_id: null,
        },
      },
      403,
    );

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).login({
      email: "a@b.com",
      password: "una-contrasena-larga",
    }),
    (error: unknown) =>
      error instanceof ApiError && error.status === 403 && error.code === "email_not_confirmed",
  );
});

test("un 500 expone el error_id para reportarlo, sin detalles internos", async () => {
  globalThis.fetch = async () =>
    jsonResponse(
      {
        error: {
          code: "internal_error",
          message: "Ocurrió un error inesperado.",
          details: null,
          error_id: "9f2c1ab4e77d",
        },
      },
      500,
    );

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getHealth(),
    (error: unknown) =>
      error instanceof ApiError &&
      error.code === "internal_error" &&
      error.errorId === "9f2c1ab4e77d",
  );
});

test("un 422 llega con los errores campo a campo en details", async () => {
  globalThis.fetch = async () =>
    jsonResponse(
      {
        error: {
          code: "validation_error",
          message: "Hay campos inválidos en la petición.",
          details: { errors: [{ loc: ["body", "email"], type: "value_error" }] },
          error_id: null,
        },
      },
      422,
    );

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).login({ email: "malo", password: "x" }),
    (error: unknown) =>
      error instanceof ApiError && error.code === "validation_error" && error.details !== null,
  );
});

test("un error que NO sigue el formato único sigue dando ApiError con el status", async () => {
  // P. ej. un 502 de un proxy delante de la API: no hay cuerpo que parsear.
  globalThis.fetch = async () => new Response("<html>Bad Gateway</html>", { status: 502 });

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getHealth(),
    (error: unknown) => error instanceof ApiError && error.status === 502 && error.code === null,
  );
});

// (Los tests de getMe se retiraron al consolidar GET /v1/auth/me en
// GET /v1/users/me — HU-1.9; getProfile cubre el mismo camino autenticado.)

test("getProfile con token inválido (401) lanza ApiError con status 401", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "No autenticado." }, 401);

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getProfile("token-malo"),
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

// --- 429 y Retry-After (HU-1.7) ----------------------------------------------

function rateLimitedResponse(retryAfter: string | null): Response {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (retryAfter !== null) {
    headers["Retry-After"] = retryAfter;
  }
  return new Response(
    JSON.stringify({
      error: {
        code: "rate_limited",
        message: "Demasiadas peticiones; espera un momento antes de reintentar.",
        details: null,
        error_id: null,
      },
    }),
    { status: 429, headers },
  );
}

test("un 429 llega como ApiError con el code y los segundos de Retry-After", async () => {
  globalThis.fetch = async () => rateLimitedResponse("42");

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).login({
      email: "ana@example.com",
      password: "un-secreto-largo",
    }),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 429 &&
      error.code === "rate_limited" &&
      error.retryAfterSeconds === 42 &&
      error.message === "Demasiadas peticiones; espera un momento antes de reintentar.",
  );
});

test("isRateLimitedError distingue el 429 de cualquier otro error", async () => {
  globalThis.fetch = async () => rateLimitedResponse("5");
  const client = new ApiClient({ baseUrl: "http://api.test" });

  const limitado = await client.getHealth().catch((error: unknown) => error);
  assert.equal(isRateLimitedError(limitado), true);

  globalThis.fetch = async () => jsonResponse({ detail: "boom" }, 500);
  const otro = await client.getHealth().catch((error: unknown) => error);
  assert.equal(isRateLimitedError(otro), false);
  assert.equal(isRateLimitedError(new Error("no es de la API")), false);
});

test("sin Retry-After el 429 sigue siendo utilizable (el cliente decide el backoff)", async () => {
  globalThis.fetch = async () => rateLimitedResponse(null);

  const error = await new ApiClient({ baseUrl: "http://api.test" })
    .getHealth()
    .catch((e: unknown) => e);

  assert.equal(isRateLimitedError(error), true);
  assert.equal((error as ApiError).retryAfterSeconds, null);
});

// --- Id de petición (HU-1.12) ------------------------------------------------

test("un error trae el id de petición de la cabecera, para poder reportarlo", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: {
          code: "internal_error",
          message: "Ocurrió un error inesperado.",
          details: null,
          error_id: "9f2c1ab4e77d",
        },
      }),
      {
        status: 500,
        headers: { "Content-Type": "application/json", [REQUEST_ID_HEADER]: "abc123" },
      },
    );

  const error = (await new ApiClient({ baseUrl: "http://api.test" })
    .getHealth()
    .catch((e: unknown) => e)) as ApiError;

  // Los dos, sin sustituirse: el errorId nombra ESE fallo, el requestId la
  // petición entera. En el log del servidor aparecen juntos.
  assert.equal(error.requestId, "abc123");
  assert.equal(error.errorId, "9f2c1ab4e77d");
});

test("el id de petición también llega en errores que no son 500", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: {
          code: "unauthenticated",
          message: "No autenticado.",
          details: null,
          error_id: null,
        },
      }),
      {
        status: 401,
        headers: { "Content-Type": "application/json", [REQUEST_ID_HEADER]: "req-401" },
      },
    );

  const error = (await new ApiClient({ baseUrl: "http://api.test" })
    .getHealth()
    .catch((e: unknown) => e)) as ApiError;

  assert.equal(error.requestId, "req-401");
  assert.equal(error.errorId, null);
});

test("sin la cabecera (p. ej. un error de proxy) el id queda en null", async () => {
  globalThis.fetch = async () => new Response("gateway caído", { status: 502 });

  const error = (await new ApiClient({ baseUrl: "http://api.test" })
    .getHealth()
    .catch((e: unknown) => e)) as ApiError;

  assert.equal(error.requestId, null);
  assert.equal(error.status, 502);
});

// --- streamChat (SSE) --------------------------------------------------------

/** Respuesta SSE con los chunks dados, como los partiría la red. */
function sseResponse(...chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });
}

function marco(payload: unknown): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

test("streamChat entrega los eventos tipados en orden y manda el Bearer", async () => {
  let request: Request | undefined;
  globalThis.fetch = async (input, init) => {
    request = new Request(String(input), init);
    return sseResponse(
      marco({ type: "start", conversation_id: "c-1", created: true }),
      marco({ type: "delta", text: "Hola, " }),
      marco({ type: "delta", text: "soy Rover." }),
      marco({ type: "done", sequence: 1 }),
    );
  };

  const eventos = [];
  let texto = "";
  for await (const evento of new ApiClient({ baseUrl: "http://api.test" }).streamChat("t0k3n", {
    message: "hola",
  })) {
    eventos.push(evento.type);
    if (evento.type === "delta") {
      texto += evento.text;
    }
  }

  assert.deepEqual(eventos, ["start", "delta", "delta", "done"]);
  assert.equal(texto, "Hola, soy Rover.");
  assert.equal(request?.url, "http://api.test/v1/chat");
  assert.equal(request?.method, "POST");
  assert.equal(request?.headers.get("Authorization"), "Bearer t0k3n");
  assert.equal(request?.headers.get("Accept"), "text/event-stream");
  assert.deepEqual(await request?.json(), { message: "hola" });
});

test("un fallo ANTES del stream llega como ApiError, no como evento", async () => {
  // El backend todavía no había mandado cabeceras: pudo usar un status normal.
  globalThis.fetch = async () =>
    jsonResponse(
      {
        error: {
          code: "not_found",
          message: "No encontramos esa conversación.",
          details: null,
          error_id: null,
        },
      },
      404,
    );

  const stream = new ApiClient({ baseUrl: "http://api.test" }).streamChat("t0k3n", {
    message: "hola",
    conversation_id: "de-otro",
  });

  await assert.rejects(
    async () => {
      for await (const evento of stream) {
        assert.fail(`no debería llegar ningún evento, llegó ${evento.type}`);
      }
    },
    (error: unknown) => error instanceof ApiError && error.code === "not_found",
  );
});

test("un fallo A MITAD llega como evento y NO lanza", async () => {
  // Para entonces puede haber texto en pantalla: lanzar lo borraría.
  globalThis.fetch = async () =>
    sseResponse(
      marco({ type: "start", conversation_id: "c-1", created: true }),
      marco({ type: "delta", text: "Te cuento: " }),
      marco({
        type: "error",
        error: {
          code: "service_unavailable",
          message: "Rover no está disponible en este momento.",
          details: null,
          error_id: null,
        },
      }),
    );

  const eventos = [];
  for await (const evento of new ApiClient({ baseUrl: "http://api.test" }).streamChat("t0k3n", {
    message: "hola",
  })) {
    eventos.push(evento);
  }

  assert.deepEqual(
    eventos.map((e) => e.type),
    ["start", "delta", "error"],
  );
  const ultimo = eventos.at(-1);
  assert.equal(ultimo?.type === "error" && ultimo.error.code, "service_unavailable");
});

test("streamChat descarta un marco ilegible y sigue", async () => {
  globalThis.fetch = async () =>
    sseResponse(
      marco({ type: "start", conversation_id: "c-1", created: false }),
      "data: {roto\n\n",
      marco({ type: "delta", text: "sigo aquí" }),
    );

  const eventos = [];
  for await (const evento of new ApiClient({ baseUrl: "http://api.test" }).streamChat("t0k3n", {
    message: "hola",
  })) {
    eventos.push(evento.type);
  }

  assert.deepEqual(eventos, ["start", "delta"]);
});

test("un 429 al abrir el stream conserva Retry-After", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: {
          code: "rate_limited",
          message: "Demasiadas peticiones.",
          details: null,
          error_id: null,
        },
      }),
      { status: 429, headers: { "Content-Type": "application/json", "Retry-After": "30" } },
    );

  const stream = new ApiClient({ baseUrl: "http://api.test" }).streamChat("t0k3n", {
    message: "hola",
  });

  await assert.rejects(
    async () => {
      for await (const evento of stream) {
        assert.fail(`no debería llegar ningún evento, llegó ${evento.type}`);
      }
    },
    (error: unknown) => isRateLimitedError(error) && (error as ApiError).retryAfterSeconds === 30,
  );
});
