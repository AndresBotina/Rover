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

test("un fallo de red lanza ApiError con status null", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };

  await assert.rejects(
    new ApiClient({ baseUrl: "http://api.test" }).getHealth(),
    (error: unknown) => error instanceof ApiError && error.status === null,
  );
});
