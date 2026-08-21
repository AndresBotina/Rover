/** Tests de los type guards de las sesiones de chat (node:test nativo). */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isChatSession,
  isChatSessionList,
  isChatSessionMessage,
  isChatSessionSummary,
} from "./session.ts";

const SUMMARY = {
  id: "0f6c2f9e-1f2a-4c3b-9d5e-8a7b6c5d4e3f",
  title: "¿Qué hago en Medellín?",
  created_at: "2026-08-20T15:04:05Z",
  updated_at: "2026-08-20T15:11:22Z",
};

const MESSAGE = {
  role: "assistant",
  content: "Tres días dan para conocerla sin correr.",
  sequence: 1,
  created_at: "2026-08-20T15:11:22Z",
};

test("acepta una cabecera de conversación válida", () => {
  assert.equal(isChatSessionSummary(SUMMARY), true);
});

test("acepta un turno del historial", () => {
  assert.equal(isChatSessionMessage(MESSAGE), true);
  assert.equal(isChatSessionMessage({ ...MESSAGE, role: "user" }), true);
});

test("rechaza un rol que no se persiste", () => {
  // `system` vive en un archivo versionado y `tool` no existe todavía: ninguno
  // llega en un historial.
  assert.equal(isChatSessionMessage({ ...MESSAGE, role: "system" }), false);
  assert.equal(isChatSessionMessage({ ...MESSAGE, role: "tool" }), false);
});

test("rechaza turnos con campos ausentes o del tipo equivocado", () => {
  assert.equal(isChatSessionMessage({ ...MESSAGE, sequence: "1" }), false);
  assert.equal(isChatSessionMessage({ ...MESSAGE, content: null }), false);
  assert.equal(isChatSessionMessage({ role: "user", content: "hola" }), false);
  assert.equal(isChatSessionMessage(null), false);
  assert.equal(isChatSessionMessage([MESSAGE]), false);
});

test("acepta la lista de conversaciones y valida cada elemento", () => {
  assert.equal(isChatSessionList({ items: [SUMMARY], limit: 50 }), true);
  assert.equal(isChatSessionList({ items: [], limit: 50 }), true);
  // Un elemento roto invalida la lista entera: mejor rechazar que pintar medio
  // listado con un hueco.
  assert.equal(isChatSessionList({ items: [SUMMARY, { id: "x" }], limit: 50 }), false);
  assert.equal(isChatSessionList({ items: [SUMMARY] }), false);
  assert.equal(isChatSessionList([SUMMARY]), false);
});

test("acepta una conversación con su historial", () => {
  assert.equal(isChatSession({ ...SUMMARY, messages: [MESSAGE] }), true);
  assert.equal(isChatSession({ ...SUMMARY, messages: [] }), true);
});

test("rechaza una conversación sin historial o con turnos rotos", () => {
  assert.equal(isChatSession(SUMMARY), false);
  assert.equal(isChatSession({ ...SUMMARY, messages: [{ role: "user" }] }), false);
});

test("un historial con tool_steps de más sigue validando, y el tipo los ignora", () => {
  // El backend no los manda; si un intermediario los añadiera, el guard no se
  // rompe — pero `ChatSessionMessage` no los declara, así que ningún cliente
  // tipado puede leerlos por descuido.
  const conExtra = { ...MESSAGE, tool_steps: [{ tool: "clima" }] };
  assert.equal(isChatSessionMessage(conExtra), true);
});
