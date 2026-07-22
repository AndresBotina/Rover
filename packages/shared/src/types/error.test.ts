/**
 * Tests del type guard del formato único de error (HU-1.8).
 *
 * Lo importante: acepta CUALQUIER error de la API con un solo guard —incluido
 * uno con un código que este cliente todavía no conoce— y rechaza lo que no
 * sigue el contrato.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { isApiErrorResponse } from "./error.ts";

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
