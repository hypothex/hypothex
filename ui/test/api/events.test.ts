import { describe, expect, spyOn, test } from "bun:test";
import { focusManager, QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { queryKeys } from "../../src/api/queries";
import { mockRoutes } from "./fetch-mock";
import { HOSTS, LOCAL_ROW } from "./phase2-fixtures";

const realFetch = globalThis.fetch;
import {
  backoffDelay,
  type Clock,
  EventStream,
  FLUSH_MS,
  HEAD_TIMEOUT_MS,
  type HxEvent,
  invalidateForEvents,
  LiveUpdates,
  keysForEvent,
  keysForEvents,
  MIRROR_RUN_UPDATED,
  readSequence,
  SEQUENCE_KEY,
  type SocketLike,
  type StreamStatus,
  useEventStream,
  useStreamStatus,
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

function harness(afterSequence?: number, resumeSequence?: number, head?: () => Promise<number | null>) {
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
    head,
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
      ["sweeps", "toy"],
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
      ["sweeps"],
    ]);
  });

  test("a mirrored remote run event refreshes that run, its project, and the hosts list", () => {
    expect(keysForEvent(ev(1, MIRROR_RUN_UPDATED, "toy", "r9"))).toEqual([
      ["overview"],
      ["tasks"],
      ["task", "toy"],
      ["runs"],
      ["run", "r9"],
      ["leaderboard", "toy"],
      ["views", "query", "toy"],
      ["compareExamples"],
      ["sweeps", "toy"],
      ["hosts"],
    ]);
  });

  test("a host event refreshes hosts and every page that shows host state", () => {
    expect(keysForEvent(ev(1, "host.state", null, null))).toEqual([
      ["hosts"],
      ["overview"],
      ["runs"],
      ["run"],
      ["sweeps"],
    ]);
  });

  test("other mirror events invalidate nothing", () => {
    expect(MIRROR_RUN_UPDATED).toBe("mirror.run_updated");
    expect(keysForEvent(ev(1, "mirror.cursor_saved", null, null))).toEqual([]);
  });

  test("a burst of mirror events after hours offline invalidates each key once", () => {
    // Runs finished while the hub was offline; on reconnect it replays 300 mirror events for 3 runs.
    const burst = Array.from({ length: 300 }, (_, i) => ev(i + 1, MIRROR_RUN_UPDATED, "toy", `r${i % 3}`));
    const keys = keysForEvents(burst);
    expect(keys).toHaveLength(12);
    expect(keys.filter((k) => k[0] === "hosts")).toEqual([["hosts"]]);
    expect(keys.filter((k) => k[0] === "run")).toEqual([
      ["run", "r0"],
      ["run", "r1"],
      ["run", "r2"],
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
      ["sweeps", "toy"],
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
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.projectSweeps("toy"),
    ];
    const miss = [
      queryKeys.run("r2"),
      queryKeys.leaderboard("other", "acc"),
      queryKeys.sweep("other", "s-1"),
      queryKeys.hosts(),
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
  test("mirror and host events refresh remote run pages and hosts, not scores of other projects", async () => {
    const client = new QueryClient();
    const hit = [
      queryKeys.hosts(),
      queryKeys.overview(),
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r9"),
      queryKeys.run("r2"),
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.sweep("other", "s-1"),
    ];
    const miss = [
      queryKeys.leaderboard("other", "acc"),
      queryKeys.views("toy", "acc"),
      queryKeys.view("toy", "acc", "route"),
      queryKeys.projects(),
    ];
    for (const key of [...hit, ...miss]) client.setQueryData(key, { seeded: true });
    invalidateForEvents(client, [
      ev(1, MIRROR_RUN_UPDATED, "toy", "r9"),
      ev(2, "host.state", null, null),
    ]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    const invalidated = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated;
    expect(hit.map(invalidated)).toEqual(hit.map(() => true));
    expect(miss.map(invalidated)).toEqual(miss.map(() => false));
  });

  test("a batch refetches each query once, even when several of its keys match it (UI-F13)", async () => {
    const client = new QueryClient();
    let fetches = 0;
    let aborted = 0;
    const observer = new QueryObserver(client, {
      queryKey: queryKeys.run("r1"),
      queryFn: async ({ signal }) => {
        fetches += 1;
        signal.addEventListener("abort", () => (aborted += 1));
        await new Promise((resolve) => setTimeout(resolve, 5));
        return { run_id: "r1" };
      },
    });
    const unsubscribe = observer.subscribe(() => {});
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetches).toBe(1);
    // `["run", "r1"]` (the run event) and `["run"]` (the host event) both match the run page
    invalidateForEvents(client, [ev(1, "run.finished", "toy", "r1"), ev(2, "host.state", null, null)]);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect([fetches, aborted]).toEqual([2, 0]);
    unsubscribe();
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

/** A head lookup the test resolves or rejects by hand. */
function deferredHead() {
  let resolve: (n: number | null) => void = () => {};
  let reject: (e: unknown) => void = () => {};
  const calls: number[] = [];
  const head = (): Promise<number | null> => {
    calls.push(1);
    return new Promise((res, rej) => {
      resolve = res;
      reject = rej;
    });
  };
  return { head, calls, resolve: (n: number | null) => resolve(n), reject: (e: unknown) => reject(e) };
}

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe("EventStream head (PERF-F10a)", () => {
  test("a fresh stream subscribes after the current last sequence: no replay", async () => {
    const d = deferredHead();
    const h = harness(undefined, undefined, d.head);
    h.stream.start();
    expect(h.sockets.length).toBe(0);
    expect(h.statuses).toEqual(["connecting"]);
    d.resolve(1_000_000);
    await tick();
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":1000000}']);
    h.last().receive({ type: "ready", last_sequence: 1_000_000 });
    expect(h.delivered).toEqual([]);
    expect(h.saved).toEqual([1_000_000]);
    h.last().receive({ type: "event", event: ev(1_000_001) });
    h.clock.advance(FLUSH_MS);
    expect(h.delivered).toEqual([[1_000_001]]);
  });

  test("reconnects resume from the last sequence without a new lookup", async () => {
    const d = deferredHead();
    const h = harness(undefined, undefined, d.head);
    h.stream.start();
    d.resolve(50);
    await tick();
    h.last().open();
    h.last().receive({ type: "ready", last_sequence: 50 });
    h.last().drop();
    h.clock.advance(3000);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":50}']);
    expect(d.calls.length).toBe(1);
  });

  test("a failed, invalid or slow lookup falls back to sequence 0", async () => {
    for (const outcome of ["reject", "null", "negative", "slow"] as const) {
      const d = deferredHead();
      const h = harness(undefined, undefined, d.head);
      h.stream.start();
      if (outcome === "reject") d.reject(new Error("404"));
      if (outcome === "null") d.resolve(null);
      if (outcome === "negative") d.resolve(-1);
      if (outcome === "slow") {
        h.clock.advance(HEAD_TIMEOUT_MS - 1);
        expect(h.sockets.length).toBe(0);
        h.clock.advance(1);
      }
      await tick();
      expect(h.sockets.length).toBe(1);
      h.last().open();
      expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":0}']);
      // a late answer after the timeout changes nothing
      d.resolve(99);
      await tick();
      expect(h.sockets.length).toBe(1);
    }
  });

  test("a stored sequence resumes without a lookup; a stale one restarts from the head", async () => {
    const d = deferredHead();
    const h = harness(undefined, 41, d.head);
    h.stream.start();
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":40}']);
    expect(d.calls.length).toBe(0);
    h.last().receive({ type: "ready", last_sequence: 40 });
    expect(d.calls.length).toBe(1);
    expect(h.sockets.length).toBe(1);
    d.resolve(7);
    await tick();
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":7}']);
  });

  test("stop() during the lookup opens no socket", async () => {
    const d = deferredHead();
    const h = harness(undefined, undefined, d.head);
    h.stream.start();
    h.stream.stop();
    d.resolve(5);
    await tick();
    h.clock.advance(60_000);
    expect(h.sockets.length).toBe(0);
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
          head: null,
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
    // one call for the batch; it matches the run's keys and nothing else
    expect(spy).toHaveBeenCalledTimes(1);
    const predicate = spy.mock.calls[0]?.[0]?.predicate;
    const matches = (queryKey: readonly unknown[]) => predicate?.({ queryKey } as never) ?? false;
    const hit = [["overview"], ["tasks"], ["task", "toy", "acc"], ["runs", {}], ["run", "r1", "logs"]];
    const hit2 = [["leaderboard", "toy"], ["views", "query", "toy"], ["compareExamples"], ["sweeps", "toy"]];
    expect([...hit, ...hit2].map(matches)).toEqual([...hit, ...hit2].map(() => true));
    expect([["run", "r2"], ["task", "other"], ["hosts"], ["views", "list"]].map(matches)).toEqual([
      false,
      false,
      false,
      false,
    ]);

    unmount();
    expect(socket.closed).toBe(true);
    expect(sockets.length).toBe(1);
  });

  test("while offline, a window focus refetches every query; while live it does not", () => {
    const client = new QueryClient();
    const spy = spyOn(client, "invalidateQueries");
    const sockets: FakeSocket[] = [];
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    const { unmount } = renderHook(
      () =>
        useEventStream({
          url: "ws://127.0.0.1:7777/api/v1/ws",
          clock: new FakeClock(),
          storage: null,
          head: null,
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
    const refocus = () =>
      act(() => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
      });
    try {
      act(() => {
        socket.open();
        socket.receive({ type: "ready", last_sequence: 0 });
      });
      refocus();
      expect(spy).not.toHaveBeenCalled();
      act(() => socket.receive({ type: "error", error: "bad subscribe" }));
      refocus();
      expect(spy.mock.calls).toEqual([[]]);
    } finally {
      focusManager.setFocused(undefined);
      unmount();
    }
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

describe("useEventStream head", () => {
  test.each([false, true])("refreshes page reads from before the head lookup (in flight: %s)", async (inFlight) => {
    const client = new QueryClient();
    const d = deferredHead();
    const sockets: FakeSocket[] = [];
    let calls = 0;
    let resolveOld: (value: string) => void = () => {};
    const observer = new QueryObserver(client, {
      queryKey: queryKeys.run("r1"),
      staleTime: Infinity,
      queryFn: () => {
        calls += 1;
        if (calls === 1) {
          return inFlight ? new Promise<string>((resolve) => { resolveOld = resolve; }) : Promise.resolve("running");
        }
        return Promise.resolve("finished");
      },
    });
    const unsubscribe = observer.subscribe(() => {});
    let viewReads = 0;
    const view = new QueryObserver(client, {
      queryKey: queryKeys.view("toy", "acc", "overview"),
      staleTime: Infinity,
      queryFn: async () => { viewReads += 1; return "saved view"; },
    });
    const unsubscribeView = view.subscribe(() => {});
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    const { unmount } = renderHook(
      () => useEventStream({
        storage: null,
        head: d.head,
        createSocket: (url) => {
          const socket = new FakeSocket(url);
          sockets.push(socket);
          return socket;
        },
      }),
      { wrapper },
    );
    try {
      await waitFor(() => expect(calls).toBe(1));
      // run.finished is sequence 10. It happened after the page request took its
      // snapshot and before /hosts selected the head, so it is not replayed.
      await act(async () => { d.resolve(10); await tick(); });
      act(() => {
        sockets[0]?.open();
        sockets[0]?.receive({ type: "ready", last_sequence: 10 });
      });
      await act(async () => { resolveOld("running"); await tick(); });
      await waitFor(() => expect(observer.getCurrentResult().data).toBe("finished"));
      expect(calls).toBe(2);
      expect(viewReads).toBe(1); // Run/host events never reload the editor's source.
    } finally {
      unmount();
      unsubscribe();
      unsubscribeView();
      client.clear();
    }
  });

  test("a new tab subscribes after the hub's last_sequence from GET /hosts (PERF-F10a)", async () => {
    const calls = mockRoutes({ "/api/v1/hosts": HOSTS });
    const client = new QueryClient();
    const sockets: FakeSocket[] = [];
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    try {
      const { unmount } = renderHook(
        () =>
          useEventStream({
            url: "ws://127.0.0.1:7777/api/v1/ws",
            clock: new FakeClock(),
            storage: null,
            createSocket: (url) => {
              const socket = new FakeSocket(url);
              sockets.push(socket);
              return socket;
            },
          }),
        { wrapper },
      );
      await waitFor(() => expect(sockets.length).toBe(1));
      act(() => sockets[0]?.open());
      expect(sockets[0]?.sent).toEqual([`{"type":"subscribe","after_sequence":${LOCAL_ROW.state.last_sequence}}`]);
      expect(calls.map((c) => c.url)).toEqual(["/api/v1/hosts"]);
      unmount();
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});

describe("LiveUpdates", () => {
  test("gives its children the stream status", () => {
    const client = new QueryClient();
    const clock = new FakeClock();
    const sockets: FakeSocket[] = [];
    function Probe() {
      return createElement("output", null, useStreamStatus());
    }
    const { unmount } = render(
      createElement(
        QueryClientProvider,
        { client },
        createElement(
          LiveUpdates,
          {
            options: {
              url: "ws://127.0.0.1:7777/api/v1/ws",
              clock,
              storage: null,
              head: null,
              createSocket: (url: string) => {
                const socket = new FakeSocket(url);
                sockets.push(socket);
                return socket;
              },
            },
          },
          createElement(Probe),
        ),
      ),
    );
    const status = () => screen.getByRole("status").textContent;
    expect(status()).toBe("connecting");
    const socket = sockets[0];
    if (!socket) throw new Error("LiveUpdates did not open a socket");
    act(() => {
      socket.open();
      socket.receive({ type: "ready", last_sequence: 0 });
    });
    expect(status()).toBe("ready");
    act(() => socket.receive({ type: "error", error: "bad subscribe" }));
    expect(status()).toBe("offline");
    unmount();
  });

  test("outside LiveUpdates the status reads ready", () => {
    function Probe() {
      return createElement("output", null, useStreamStatus());
    }
    const { unmount } = render(createElement(Probe));
    expect(screen.getByRole("status").textContent).toBe("ready");
    unmount();
  });
});
