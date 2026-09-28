import { describe, expect, spyOn, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { queryKeys } from "../../src/api/queries";
import {
  backoffDelay,
  type Clock,
  EventStream,
  FLUSH_MS,
  type HxEvent,
  invalidateForEvents,
  keysForEvent,
  keysForEvents,
  readSequence,
  SEQUENCE_KEY,
  type SocketLike,
  type StreamStatus,
  useEventStream,
  writeSequence,
} from "../../src/api/events";

class FakeSocket implements SocketLike {
  readonly url: string;
  readyState = 0;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  readonly sent: string[] = [];
  closed = false;

  constructor(url: string) {
    this.url = url;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  receive(message: unknown): void {
    this.receiveRaw(JSON.stringify(message));
  }

  receiveRaw(data: string): void {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  /** The network drops the connection (the server did not ask to close). */
  drop(): void {
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }
}

class FakeClock implements Clock {
  now = 0;
  private nextId = 1;
  private readonly timers = new Map<number, { at: number; fn: () => void }>();

  setTimeout(fn: () => void, ms: number): number {
    const id = this.nextId++;
    this.timers.set(id, { at: this.now + ms, fn });
    return id;
  }

  clearTimeout(handle: unknown): void {
    this.timers.delete(handle as number);
  }

  /** Move time forward, firing due timers in time order (ties in creation order). */
  advance(ms: number): void {
    const end = this.now + ms;
    for (;;) {
      let nextId = -1;
      let nextAt = Number.POSITIVE_INFINITY;
      for (const [id, timer] of this.timers) {
        if (timer.at <= end && timer.at < nextAt) {
          nextId = id;
          nextAt = timer.at;
        }
      }
      const timer = this.timers.get(nextId);
      if (!timer) break;
      this.timers.delete(nextId);
      this.now = nextAt;
      timer.fn();
    }
    this.now = end;
  }
}

function ev(
  sequence: number,
  type = "run.finished",
  project: string | null = "toy",
  run_id: string | null = "r1",
): HxEvent {
  return { sequence, type, project, run_id, payload: {}, created_at: "2026-09-27T10:00:00Z" };
}

function harness(afterSequence?: number, resumeSequence?: number) {
  const clock = new FakeClock();
  const sockets: FakeSocket[] = [];
  const delivered: number[][] = [];
  const statuses: StreamStatus[] = [];
  const saved: number[] = [];
  const stream = new EventStream({
    url: "ws://127.0.0.1:7777/api/v1/ws",
    clock,
    afterSequence,
    resumeSequence,
    createSocket: (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    onEvents: (events) => delivered.push(events.map((e) => e.sequence)),
    onStatus: (status) => statuses.push(status),
    onSequence: (sequence) => saved.push(sequence),
  });
  const last = (): FakeSocket => {
    const socket = sockets.at(-1);
    if (!socket) throw new Error("no socket was created");
    return socket;
  };
  return { stream, clock, sockets, delivered, statuses, saved, last };
}

/** An in-memory `Storage` stand-in. */
function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
  };
}

describe("backoffDelay", () => {
  test("follows 3/4/8/16 s and stays at 16 s", () => {
    expect([0, 1, 2, 3, 4, 9].map(backoffDelay)).toEqual([3000, 4000, 8000, 16000, 16000, 16000]);
  });
});

describe("keysForEvent", () => {
  test("a run event invalidates run lists, the run, and its project's boards and views", () => {
    expect(keysForEvent(ev(1, "run.finished", "toy", "r1"))).toEqual([
      ["overview"],
      ["tasks"],
      ["task", "toy"],
      ["runs"],
      ["run", "r1"],
      ["leaderboard", "toy"],
      ["views", "query", "toy"],
      ["compareExamples"],
    ]);
  });

  test("a run event without project or run id invalidates the families", () => {
    expect(keysForEvent(ev(1, "run.lost", null, null))).toEqual([
      ["overview"],
      ["tasks"],
      ["task"],
      ["runs"],
      ["leaderboard"],
      ["views", "query"],
      ["compareExamples"],
    ]);
  });

  test("a non-run event invalidates nothing", () => {
    expect(keysForEvent(ev(1, "test.event", null, null))).toEqual([]);
  });

  test("keysForEvents drops duplicate keys and keeps first-seen order", () => {
    const keys = keysForEvents([
      ev(1, "run.finished", "toy", "r1"),
      ev(2, "run.score_added", "toy", "r1"),
      ev(3, "run.started", "toy", "r2"),
    ]);
    expect(keys).toEqual([
      ["overview"],
      ["tasks"],
      ["task", "toy"],
      ["runs"],
      ["run", "r1"],
      ["leaderboard", "toy"],
      ["views", "query", "toy"],
      ["compareExamples"],
      ["run", "r2"],
    ]);
  });

  test("a run event refreshes every page query of that run and project, and no view text", async () => {
    const client = new QueryClient();
    const hit = [
      queryKeys.overview(),
      queryKeys.tasks(),
      queryKeys.task("toy", "acc"),
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r1"),
      queryKeys.runLogs("r1", "stderr"),
      queryKeys.runTrace("r1", "ex-1"),
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.viewQuery("toy", "acc", { name: "overview" }),
      queryKeys.compareExamples("r0", "r1", "accuracy"),
    ];
    const miss = [
      queryKeys.run("r2"),
      queryKeys.leaderboard("other", "acc"),
      queryKeys.views("toy", "acc"),
      queryKeys.view("toy", "acc", "route"),
      queryKeys.taskKind("toy", "acc"),
      queryKeys.projects(),
    ];
    for (const key of [...hit, ...miss]) client.setQueryData(key, { seeded: true });
    invalidateForEvents(client, [ev(1, "run.note_added", "toy", "r1")]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    const invalidated = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated;
    expect(hit.map(invalidated)).toEqual(hit.map(() => true));
    expect(miss.map(invalidated)).toEqual(miss.map(() => false));
  });
});

describe("stored sequence", () => {
  test("readSequence accepts only positive integers; writeSequence ignores storage errors", () => {
    expect(readSequence(memoryStorage({ [SEQUENCE_KEY]: "41" }))).toBe(41);
    for (const bad of ["", "abc", "-3", "1.5", "0"]) {
      expect(readSequence(memoryStorage({ [SEQUENCE_KEY]: bad }))).toBe(0);
    }
    expect(readSequence(memoryStorage())).toBe(0);
    expect(readSequence(null)).toBe(0);
    const broken = {
      getItem: (): string | null => {
        throw new Error("SecurityError");
      },
      setItem: (): void => {
        throw new Error("QuotaExceededError");
      },
    };
    expect(readSequence(broken)).toBe(0);
    expect(() => writeSequence(broken, 5)).not.toThrow();
    const store = memoryStorage();
    writeSequence(store, 42);
    expect(store.data.get(SEQUENCE_KEY)).toBe("42");
  });
});

describe("EventStream", () => {
  test("resumes from a stored sequence without replaying or redelivering it", () => {
    const h = harness(undefined, 41);
    h.stream.start();
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":40}']);
    h.last().receive({ type: "event", event: ev(41) });
    h.last().receive({ type: "event", event: ev(42) });
    h.last().receive({ type: "ready", last_sequence: 42 });
    expect(h.delivered).toEqual([[42]]);
    expect(h.stream.sequence).toBe(42);
    expect(h.saved).toEqual([42]);
    expect(h.sockets.length).toBe(1);
  });

  test("a stored sequence the server does not have restarts from 0 at once", () => {
    const h = harness(undefined, 41);
    h.stream.start();
    const first = h.last();
    first.open();
    first.receive({ type: "ready", last_sequence: 40 });
    expect(first.closed).toBe(true);
    expect(h.sockets.length).toBe(2);
    expect(h.delivered).toEqual([]);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":0}']);
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "ready", last_sequence: 1 });
    expect(h.delivered).toEqual([[1]]);
    expect(h.saved).toEqual([1]);
    expect(h.statuses).toEqual(["connecting", "connected", "connecting", "connected", "ready"]);
  });

  test("subscribes after the given sequence once the socket opens", () => {
    const fresh = harness();
    fresh.stream.start();
    expect(fresh.last().sent).toEqual([]);
    fresh.last().open();
    expect(fresh.last().sent).toEqual(['{"type":"subscribe","after_sequence":0}']);

    const resumed = harness(41);
    resumed.stream.start();
    resumed.last().open();
    expect(resumed.last().sent).toEqual(['{"type":"subscribe","after_sequence":41}']);
    expect(resumed.last().url).toBe("ws://127.0.0.1:7777/api/v1/ws");
  });

  test("buffers replayed events until ready, then delivers them once", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "event", event: ev(2) });
    expect(h.delivered).toEqual([]);
    h.last().receive({ type: "ready", last_sequence: 2 });
    expect(h.delivered).toEqual([[1, 2]]);
    expect(h.statuses).toEqual(["connecting", "connected", "ready"]);
    expect(h.stream.sequence).toBe(2);
  });

  test("batches live events that arrive within FLUSH_MS", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "ready", last_sequence: 2 });
    h.last().receive({ type: "event", event: ev(3) });
    h.last().receive({ type: "event", event: ev(4) });
    h.clock.advance(FLUSH_MS - 1);
    expect(h.delivered).toEqual([]);
    h.clock.advance(1);
    expect(h.delivered).toEqual([[3, 4]]);
  });

  test("drops duplicate and old sequences", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "ready", last_sequence: 4 });
    for (const sequence of [3, 4, 5, 5]) h.last().receive({ type: "event", event: ev(sequence) });
    h.clock.advance(FLUSH_MS);
    expect(h.delivered).toEqual([[5]]);
  });

  test("reconnects after 3, 4, 8, 16, 16 s while the connection keeps failing", () => {
    const h = harness();
    h.stream.start();
    expect(h.sockets.length).toBe(1);
    let expected = 1;
    for (const delay of [3000, 4000, 8000, 16000, 16000]) {
      h.last().drop();
      expect(h.statuses.at(-1)).toBe("offline");
      h.clock.advance(delay - 1);
      expect(h.sockets.length).toBe(expected);
      h.clock.advance(1);
      expected += 1;
      expect(h.sockets.length).toBe(expected);
      expect(h.statuses.at(-1)).toBe("connecting");
    }
  });

  test("resubscribes after the last seen sequence", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "event", event: ev(2) });
    h.last().receive({ type: "ready", last_sequence: 2 });
    h.last().receive({ type: "event", event: ev(3) });
    h.last().drop();
    h.clock.advance(3000);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":3}']);
  });

  test("keeps replayed events across a drop before ready", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "event", event: ev(1) });
    h.last().drop();
    h.clock.advance(3000);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":1}']);
    expect(h.delivered).toEqual([]);
    h.last().receive({ type: "ready", last_sequence: 1 });
    expect(h.delivered).toEqual([[1]]);
  });

  test("resets the backoff after 30 s of stable connection, and not before", () => {
    const h = harness();
    h.stream.start();
    h.last().drop();
    h.clock.advance(3000); // socket 2
    h.last().drop();
    h.clock.advance(4000); // socket 3, next delay would be 8 s
    h.last().open();
    h.clock.advance(29_999);
    h.last().drop();
    h.clock.advance(7_999);
    expect(h.sockets.length).toBe(3);
    h.clock.advance(1);
    expect(h.sockets.length).toBe(4); // not reset: 8 s
    h.last().open();
    h.clock.advance(30_000);
    h.last().drop();
    h.clock.advance(2_999);
    expect(h.sockets.length).toBe(4);
    h.clock.advance(1);
    expect(h.sockets.length).toBe(5); // reset: 3 s
  });

  test("ignores messages from a replaced socket", () => {
    const h = harness();
    h.stream.start();
    const first = h.last();
    first.open();
    first.receive({ type: "ready", last_sequence: 0 });
    first.drop();
    h.clock.advance(3000);
    first.receive({ type: "event", event: ev(9) });
    h.clock.advance(FLUSH_MS);
    expect(h.delivered).toEqual([]);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":0}']);
  });

  test("stops retrying after a server error message", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "error", error: "first message must be {type: subscribe}" });
    expect(h.last().closed).toBe(true);
    expect(h.statuses.at(-1)).toBe("offline");
    h.clock.advance(60_000);
    expect(h.sockets.length).toBe(1);
  });

  test("stop() closes an open socket and never reconnects", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.stream.stop();
    expect(h.last().closed).toBe(true);
    h.clock.advance(60_000);
    expect(h.sockets.length).toBe(1);
    expect(h.statuses).toEqual(["connecting", "connected"]);
  });

  test("stop() while connecting closes only after open", () => {
    const h = harness();
    h.stream.start();
    h.stream.stop();
    expect(h.last().closed).toBe(false);
    h.last().open();
    expect(h.last().closed).toBe(true);
    expect(h.last().sent).toEqual([]);
    h.clock.advance(60_000);
    expect(h.sockets.length).toBe(1);
  });

  test("ignores malformed messages", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receiveRaw("not json");
    h.last().receiveRaw("null");
    h.last().receiveRaw('{"type":"event","event":{"sequence":"7","type":"run.finished"}}');
    h.last().receiveRaw('{"type":"event"}');
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "ready", last_sequence: 1 });
    expect(h.delivered).toEqual([[1]]);
  });
});

describe("useEventStream", () => {
  test("invalidates the mapped keys, reports status, and closes on unmount", () => {
    const client = new QueryClient();
    const spy = spyOn(client, "invalidateQueries");
    const clock = new FakeClock();
    const sockets: FakeSocket[] = [];
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    const { result, unmount } = renderHook(
      () =>
        useEventStream({
          url: "ws://127.0.0.1:7777/api/v1/ws",
          clock,
          storage: null,
          createSocket: (url) => {
            const socket = new FakeSocket(url);
            sockets.push(socket);
            return socket;
          },
        }),
      { wrapper },
    );
    const socket = sockets[0];
    if (!socket) throw new Error("hook did not open a socket");
    expect(result.current).toBe("connecting");

    act(() => {
      socket.open();
      socket.receive({ type: "ready", last_sequence: 7 });
    });
    expect(result.current).toBe("ready");
    expect(spy).not.toHaveBeenCalled();

    act(() => {
      socket.receive({ type: "event", event: ev(8, "run.score_added", "toy", "r1") });
      socket.receive({ type: "event", event: ev(9, "run.finished", "toy", "r1") });
      clock.advance(FLUSH_MS);
    });
    expect(spy.mock.calls.map((call) => call[0])).toEqual([
      { queryKey: ["overview"] },
      { queryKey: ["tasks"] },
      { queryKey: ["task", "toy"] },
      { queryKey: ["runs"] },
      { queryKey: ["run", "r1"] },
      { queryKey: ["leaderboard", "toy"] },
      { queryKey: ["views", "query", "toy"] },
      { queryKey: ["compareExamples"] },
    ]);

    unmount();
    expect(socket.closed).toBe(true);
    expect(sockets.length).toBe(1);
  });

  test("resumes from sessionStorage and saves the last delivered sequence", () => {
    const client = new QueryClient();
    const storage = memoryStorage({ [SEQUENCE_KEY]: "7" });
    const sockets: FakeSocket[] = [];
    const clock = new FakeClock();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    const { unmount } = renderHook(
      () =>
        useEventStream({
          url: "ws://127.0.0.1:7777/api/v1/ws",
          clock,
          storage,
          createSocket: (url) => {
            const socket = new FakeSocket(url);
            sockets.push(socket);
            return socket;
          },
        }),
      { wrapper },
    );
    const socket = sockets[0];
    if (!socket) throw new Error("hook did not open a socket");
    act(() => socket.open());
    expect(socket.sent).toEqual(['{"type":"subscribe","after_sequence":6}']);
    act(() => {
      socket.receive({ type: "event", event: ev(7) });
      socket.receive({ type: "ready", last_sequence: 7 });
      socket.receive({ type: "event", event: ev(8) });
      socket.receive({ type: "event", event: ev(9) });
      clock.advance(FLUSH_MS);
    });
    expect(storage.data.get(SEQUENCE_KEY)).toBe("9");
    unmount();
  });
});
