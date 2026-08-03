/**
 * Tests del type guard del formato único de error (HU-1.8).
 *
 * Lo importante: acepta CUALQUIER error de la API con un solo guard —incluido
 * uno con un código que este cliente todavía no conoce— y rechaza lo que no
 * sigue el contrato.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { isApiErrorResponse, parseRetryAfter, RATE_LIMITED } from "./error.ts";

const ERROR_401 = {
  error: {
    code: "unauthenticated",
    message: "No autenticado.",
    details: null,
    error_id: null,
  },
};

test("acepta un error simple (sin detalles ni error_id)", () => {
  assert.equal(isApiErrorResponse(ERROR_401), true);
});

test("acepta un 422 con detalles campo a campo", () => {
  assert.equal(
    isApiErrorResponse({
      error: {
        code: "validation_error",
        message: "Hay campos inválidos en la petición.",
        details: { errors: [{ loc: ["body", "email"], type: "value_error" }] },
        error_id: null,
      },
    }),
    true,
  );
});

test("acepta un 500 con error_id", () => {
  assert.equal(
    isApiErrorResponse({
      error: {
        code: "internal_error",
        message: "Ocurrió un error inesperado.",
        details: null,
        error_id: "9f2c1ab4e77d",
      },
    }),
    true,
  );
});

test("acepta un código que este cliente aún no conoce (compatibilidad futura)", () => {
  assert.equal(
    isApiErrorResponse({
      error: { code: "codigo_del_futuro", message: "…", details: null, error_id: null },
    }),
    true,
  );
});

test("rechaza un cuerpo sin el envoltorio error", () => {
  assert.equal(isApiErrorResponse({ code: "not_found", message: "…" }), false);
  assert.equal(isApiErrorResponse({ detail: "No autenticado." }), false);
});

test("rechaza si faltan campos o tienen el tipo equivocado", () => {
  assert.equal(isApiErrorResponse({ error: { code: "x" } }), false);
  assert.equal(isApiErrorResponse({ error: { code: 42, message: "x" } }), false);
  assert.equal(
    isApiErrorResponse({ error: { code: "x", message: "y", details: [], error_id: null } }),
    false,
  );
  assert.equal(
    isApiErrorResponse({ error: { code: "x", message: "y", details: null, error_id: 7 } }),
    false,
  );
});

test("rechaza valores que no son objeto", () => {
  assert.equal(isApiErrorResponse(null), false);
  assert.equal(isApiErrorResponse("error"), false);
  assert.equal(isApiErrorResponse(undefined), false);
});

// --- Retry-After del 429 (HU-1.7) --------------------------------------------

test("parseRetryAfter entiende la forma en segundos (la que manda esta API)", () => {
  assert.equal(parseRetryAfter("30"), 30);
  assert.equal(parseRetryAfter("  30  "), 30);
  assert.equal(parseRetryAfter("0"), 0);
});

test("parseRetryAfter entiende una fecha HTTP y la convierte a segundos", () => {
  const ahora = new Date("2026-08-03T10:00:00Z");

  assert.equal(parseRetryAfter("Mon, 03 Aug 2026 10:00:45 GMT", ahora), 45);
});

test("parseRetryAfter nunca devuelve segundos negativos", () => {
  const ahora = new Date("2026-08-03T10:00:00Z");

  // Una fecha ya pasada significa "reintenta ya", no "reintenta en el pasado".
  assert.equal(parseRetryAfter("Mon, 03 Aug 2026 09:59:00 GMT", ahora), 0);
});

test("parseRetryAfter devuelve null si falta la cabecera o no se entiende", () => {
  assert.equal(parseRetryAfter(null), null);
  assert.equal(parseRetryAfter(undefined), null);
  assert.equal(parseRetryAfter(""), null);
  assert.equal(parseRetryAfter("pronto"), null);
  // Nada de aceptar a medias un número mal escrito: o son dígitos, o no vale.
  assert.equal(parseRetryAfter("12abc"), null);
  assert.equal(parseRetryAfter("-5"), null);
});

test("rate_limited es un código conocido del catálogo", () => {
  assert.equal(RATE_LIMITED, "rate_limited");
  assert.equal(
    isApiErrorResponse({
      error: {
        code: RATE_LIMITED,
        message: "Demasiadas peticiones.",
        details: null,
        error_id: null,
      },
    }),
    true,
  );
});
