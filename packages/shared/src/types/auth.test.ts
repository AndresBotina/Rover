/**
 * Tests del type guard isRegisterResponse (node:test nativo, sin deps extra).
 * Cubre las DOS formas de la unión discriminada y el rechazo de formas
 * incoherentes.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { isRegisterResponse } from "./auth.ts";

const USER = { id: "11111111-1111-1111-1111-111111111111", email: "a@b.com" };
const SESSION = { access_token: "at", refresh_token: "rt", token_type: "bearer" };

test("acepta la forma 'active' con sesión válida", () => {
  assert.equal(isRegisterResponse({ status: "active", user: USER, session: SESSION }), true);
});

test("acepta la forma 'pending_email_confirmation' con session null", () => {
  assert.equal(
    isRegisterResponse({ status: "pending_email_confirmation", user: USER, session: null }),
    true,
  );
});

test("rechaza 'active' sin sesión (combinación incoherente)", () => {
  assert.equal(isRegisterResponse({ status: "active", user: USER, session: null }), false);
});

test("rechaza 'pending_email_confirmation' con sesión presente", () => {
  assert.equal(
    isRegisterResponse({ status: "pending_email_confirmation", user: USER, session: SESSION }),
    false,
  );
});

test("rechaza un status desconocido", () => {
  assert.equal(isRegisterResponse({ status: "otra_cosa", user: USER, session: SESSION }), false);
});

test("rechaza si falta el status (no se puede discriminar)", () => {
  assert.equal(isRegisterResponse({ user: USER, session: SESSION }), false);
});

test("rechaza si el usuario tiene forma inválida", () => {
  assert.equal(
    isRegisterResponse({ status: "active", user: { id: "x" }, session: SESSION }),
    false,
  );
});

test("rechaza valores que no son objeto", () => {
  assert.equal(isRegisterResponse(null), false);
  assert.equal(isRegisterResponse("register"), false);
});
