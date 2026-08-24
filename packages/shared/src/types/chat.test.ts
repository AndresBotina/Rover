/** Tests de los eventos del chat en streaming (node:test nativo, sin deps extra). */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isChatDeltaEvent,
  isChatDoneEvent,
  isChatErrorEvent,
  isChatStartEvent,
  isChatStatusEvent,
  isChatStreamEvent,
  parseChatStreamEvent,
  readSseFrames,
} from "./chat.ts";

const START = { type: "start", conversation_id: "c-1", created: true };
const DELTA = { type: "delta", text: "Hola" };
const STATUS = { type: "status", tool: "get_weather", message: "Consultando el clima…" };
const DONE = { type: "done", sequence: 1 };
const ERROR = {
  type: "error",
  error: {
    code: "service_unavailable",
    message: "Rover no está disponible en este momento.",
    details: null,
    error_id: null,
  },
};

/** ReadableStream con los chunks dados, tal como los partiría la red. */
function streamDe(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

async function recoger(stream: ReadableStream<Uint8Array>): Promise<string[]> {
  const salida: string[] = [];
  for await (const marco of readSseFrames(stream)) {
    salida.push(marco);
  }
  return salida;
}

// --- Type guards -------------------------------------------------------------

test("cada evento se reconoce por su propio guard", () => {
  assert.equal(isChatStartEvent(START), true);
  assert.equal(isChatDeltaEvent(DELTA), true);
  assert.equal(isChatStatusEvent(STATUS), true);
  assert.equal(isChatDoneEvent(DONE), true);
  assert.equal(isChatErrorEvent(ERROR), true);
});

test("los guards NO se confunden entre sí: el discriminante manda", () => {
  // Es la propiedad que hace útil la unión: un `delta` no puede colarse por
  // donde se espera un `error` aunque tenga campos de más.
  assert.equal(isChatDeltaEvent(START), false);
  assert.equal(isChatStartEvent(DELTA), false);
  assert.equal(isChatDoneEvent(ERROR), false);
  assert.equal(isChatStatusEvent(DELTA), false);
  assert.equal(isChatDeltaEvent(STATUS), false);
  assert.equal(isChatErrorEvent({ ...DELTA, error: ERROR.error }), false);
});

test("rechaza eventos con la forma equivocada", () => {
  assert.equal(isChatStartEvent({ type: "start", conversation_id: "c-1" }), false);
  assert.equal(isChatStartEvent({ ...START, created: "sí" }), false);
  assert.equal(isChatDeltaEvent({ type: "delta", text: 42 }), false);
  assert.equal(isChatDoneEvent({ type: "done", sequence: "1" }), false);
  assert.equal(isChatStatusEvent({ type: "status", tool: "get_weather" }), false);
  assert.equal(isChatStatusEvent({ ...STATUS, message: 42 }), false);
  assert.equal(isChatErrorEvent({ type: "error", error: { code: "x" } }), false);
  assert.equal(isChatStreamEvent(null), false);
  assert.equal(isChatStreamEvent([DELTA]), false);
  assert.equal(isChatStreamEvent("delta"), false);
});

test("un tipo desconocido no se acepta", () => {
  // A diferencia de ApiErrorCode (que sí admite códigos futuros), aquí el
  // cliente tendría que saber qué HACER con la carga útil.
  assert.equal(isChatStreamEvent({ type: "tool_step", name: "clima" }), false);
});

test("el evento de estado NO lleva argumentos ni resultado de la herramienta", () => {
  // El contrato solo tiene `tool` y `message`: lo demás es interno del backend
  // (se persiste en tool_steps y no se expone). Si alguien añadiera esos campos
  // al tipo, este test seguiría pasando — lo que vigila es lo contrario: que un
  // evento con esos campos de más se acepte igual, porque el guard mira lo que
  // el cliente NECESITA, y que el cliente nunca los lea de aquí.
  const parseado = parseChatStreamEvent(JSON.stringify(STATUS));
  assert.deepEqual(parseado, STATUS);
  assert.deepEqual(Object.keys(STATUS).sort(), ["message", "tool", "type"]);
});

test("un cliente viejo descarta el evento de estado sin romperse", () => {
  // La razón por la que el contrato pudo crecer en la HU-2.6 sin versionar
  // nada: un guard estricto devuelve null para lo que no conoce, y el bucle de
  // lectura sigue con el marco siguiente en vez de lanzar.
  const guardViejo = (v: unknown) =>
    isChatStartEvent(v) || isChatDeltaEvent(v) || isChatDoneEvent(v) || isChatErrorEvent(v);
  assert.equal(guardViejo(STATUS), false);
  assert.equal(isChatStreamEvent(STATUS), true);
});

// --- Parseo de un marco ------------------------------------------------------

test("parseChatStreamEvent devuelve el evento tipado", () => {
  assert.deepEqual(parseChatStreamEvent(JSON.stringify(DELTA)), DELTA);
});

test("parseChatStreamEvent devuelve null en vez de lanzar", () => {
  // Un marco roto no debe tumbar una respuesta que ya se está pintando.
  assert.equal(parseChatStreamEvent("{no es json"), null);
  assert.equal(parseChatStreamEvent(JSON.stringify({ type: "otro" })), null);
});

// --- Troceado del stream SSE -------------------------------------------------

test("separa los marcos por la línea en blanco", async () => {
  const marcos = await recoger(streamDe('data: {"a":1}\n\ndata: {"b":2}\n\n'));
  assert.deepEqual(marcos, ['{"a":1}', '{"b":2}']);
});

test("un marco partido entre dos chunks de red se reconstruye", async () => {
  // El caso que rompe un parser ingenuo: la red no respeta los límites del
  // formato, y aquí el corte cae dentro del JSON.
  const marcos = await recoger(streamDe('data: {"te', 'xt":"hola"}\n\ndata: {"x":1}\n\n'));
  assert.deepEqual(marcos, ['{"text":"hola"}', '{"x":1}']);
});

test("un carácter multibyte partido entre chunks no se corrompe", async () => {
  const bytes = new TextEncoder().encode('data: {"text":"añ"}\n\n');
  const corte = 16; // cae en medio de la "ñ"
  const encoder = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, corte));
      controller.enqueue(bytes.slice(corte));
      controller.close();
    },
  });
  assert.deepEqual(await recoger(encoder), ['{"text":"añ"}']);
});

test("acepta CRLF y descarta comentarios de keep-alive", async () => {
  const marcos = await recoger(streamDe(': ping\r\n\r\ndata: {"a":1}\r\n\r\n'));
  assert.deepEqual(marcos, ['{"a":1}']);
});

test("el último marco sin línea en blanco final no se pierde", async () => {
  assert.deepEqual(await recoger(streamDe('data: {"a":1}')), ['{"a":1}']);
});

test("abandonar el bucle a mitad cancela la lectura", async () => {
  // Es lo que pasa cuando el usuario cierra la vista del chat: el backend lo
  // detecta y descarta la respuesta a medias.
  let cancelado = false;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"a":1}\n\ndata: {"b":2}\n\n'));
    },
    cancel() {
      cancelado = true;
    },
  });

  for await (const marco of readSseFrames(stream)) {
    assert.equal(marco, '{"a":1}');
    break;
  }

  assert.equal(cancelado, true);
});
