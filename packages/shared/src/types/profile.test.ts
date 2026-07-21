/** Tests del type guard isProfile (node:test nativo, sin deps extra). */

import assert from "node:assert/strict";
import { test } from "node:test";

import { isProfile } from "./profile.ts";

const PROFILE = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "a@b.com",
  plan: "free",
  preferences: {},
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

test("acepta un perfil válido (plan free o pro)", () => {
  assert.equal(isProfile(PROFILE), true);
  assert.equal(isProfile({ ...PROFILE, plan: "pro" }), true);
});

test("rechaza plan desconocido", () => {
  assert.equal(isProfile({ ...PROFILE, plan: "enterprise" }), false);
});

test("rechaza preferences que no es un objeto", () => {
  assert.equal(isProfile({ ...PROFILE, preferences: [1, 2] }), false);
  assert.equal(isProfile({ ...PROFILE, preferences: "no" }), false);
  assert.equal(isProfile({ ...PROFILE, preferences: null }), false);
});

test("rechaza si faltan campos o no es objeto", () => {
  assert.equal(isProfile({ id: "x", email: "a@b.com", plan: "free" }), false);
  assert.equal(isProfile(null), false);
  assert.equal(isProfile("profile"), false);
});
