import { afterEach, expect, test } from "bun:test";
import { EventStream, type SocketLike, type Clock } from "../../src/api/events";
import { auth } from "../../src/api/auth";
import { websocketTicket } from "../../src/api/client";
const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; auth.select(null); });
function pending<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void; const promise = new Promise<T>((fn) => { resolve = fn; }); return { promise, resolve };
}
class Socket implements SocketLike {
  readyState = 1; onopen = null; onmessage = null; onerror = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  send(): void {} close(): void { this.readyState = 3; }
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
test("each reconnect requests a fresh ticket; only fixed protocol plus ticket, clean URL", async () => {
  const tasks: {fn: () => void; ms: number}[] = []; const sockets: Socket[] = []; const calls: string[][] = [];
  const clock: Clock = { setTimeout(fn, ms) { tasks.push({fn, ms}); return fn; }, clearTimeout() {} };
  let count = 0;
  const stream = new EventStream({ url: "ws://example.test/api/v1/ws", onEvents() {}, clock,
    ticket: async () => `ticket-${++count}`,
    createSocket: (url, protocols) => { expect(url).toBe("ws://example.test/api/v1/ws"); calls.push(protocols); const s = new Socket(); sockets.push(s); return s; } });
  stream.start(); await tick(); expect(calls).toEqual([["hypothex.v1", "hx-ticket.ticket-1"]]);
  sockets[0]!.onclose?.(new CloseEvent("close"));
  expect(count).toBe(1); expect(tasks[0]!.ms).toBe(3000);
  tasks[0]!.fn(); await tick(); expect(calls[1]).toEqual(["hypothex.v1", "hx-ticket.ticket-2"]);
  stream.stop();
});
test("stop/credential replacement aborts pending ticket and ignores late answer", async () => {
  for (const stop of [true, false]) {
    const wait = pending<string>(); let opened = 0; let signal!: AbortSignal;
    const stream = new EventStream({ url: "ws://example.test/api/v1/ws", onEvents() {},
      ticket: (s) => { signal = s; return wait.promise; }, createSocket: () => { opened++; return new Socket(); } });
    stream.start(); if (stop) stream.stop(); else auth.select("replacement");
    expect(signal.aborted).toBe(true); wait.resolve("late-ticket"); await tick(); expect(opened).toBe(0);
    stream.stop();
  }
});
test("noauth uses fixed protocol; ticket failure retries with backoff", async () => {
  const tasks: {fn: () => void; ms: number}[] = []; const protocols: string[][] = []; let attempts = 0;
  const stream = new EventStream({ url: "ws://example.test/api/v1/ws", onEvents() {},
    clock: { setTimeout(fn, ms) { tasks.push({fn,ms}); return fn; }, clearTimeout() {} },
    ticket: async () => { if (++attempts === 1) throw new Error("temporary"); return null; },
    createSocket: (_url, p) => { protocols.push(p); return new Socket(); } });
  stream.start(); await tick(); expect(attempts).toBe(1); expect(tasks[0]!.ms).toBe(3000);
  tasks[0]!.fn(); await tick(); expect(protocols).toEqual([["hypothex.v1"]]); stream.stop();
});
test("ticket POST authenticates in header, rejects malformed body, never returns root token", async () => {
  auth.select("synthetic-root");
  globalThis.fetch = (async (url: RequestInfo | URL, init?: RequestInit) => {
    expect(String(url)).toBe("/api/v1/auth/ws-ticket"); expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer synthetic-root");
    return new Response(JSON.stringify({ ticket: "short-ticket", expires_in: 30 }));
  }) as unknown as typeof fetch;
  expect(await websocketTicket()).toBe("short-ticket");
  globalThis.fetch = (async () => new Response('{"ticket":"bad value","expires_in":30}')) as unknown as typeof fetch;
  await expect(websocketTicket()).rejects.toThrow("Invalid live stream response");
});

test("a real issuer 401 locks auth and stops reconnect attempts", async () => {
  const generation = auth.select("expired-synthetic"); auth.accept(generation);
  const tasks: number[] = []; let opens = 0;
  globalThis.fetch = (async () => new Response("", { status: 401 })) as unknown as typeof fetch;
  const stream = new EventStream({ url: "ws://example.test/api/v1/ws", onEvents() {},
    clock: { setTimeout(_fn, ms) { tasks.push(ms); return ms; }, clearTimeout() {} },
    createSocket: () => { opens++; return new Socket(); } });
  stream.start();
  for (let i = 0; i < 10; i++) await Promise.resolve();
  expect(auth.snapshot().status).toBe("locked"); expect(opens).toBe(0); expect(tasks).toEqual([]);
  stream.stop();
});
