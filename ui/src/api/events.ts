/**
 * Live updates over `/api/v1/ws`.
 *
 * One stream per app: subscribe with `after_sequence`, receive the replay, then live
 * events. Reconnects with 3/4/8/16 s backoff (reset after 30 s stable), drops duplicate
 * sequences, and turns events into TanStack Query invalidations (spec 5.3, 8.2). The last
 * delivered sequence is kept in `sessionStorage`, so a page load resumes there; a new tab
 * starts after the server's newest sequence (`fetchLastSequence`). Neither replays the
 * whole event log.
 */
import {
  focusManager,
  partialMatchKey,
  type QueryClient,
  type QueryKey,
  useQueryClient,
} from "@tanstack/react-query";
import { createContext, createElement, type ReactNode, useContext, useEffect, useRef, useState } from "react";

import { wsUrl } from "./client";
import type { HxEvent, WsMessage } from "./models";
import { noteLostReasons } from "./lostReasons";
import {
  fetchLastSequence,
  HOST_EVENT_INVALIDATES,
  REMOTE_RUN_INVALIDATES,
  RUN_EVENT_INVALIDATES,
} from "./queries";

/** One entry of the server's event log (`hypothex.core.events.Event`). */
export type { HxEvent };

/** Messages the server sends on `/api/v1/ws`. */
export type ServerMessage = WsMessage;

/** `connected`: open and subscribed. `ready`: replay done, live from here on. */
export type StreamStatus = "connecting" | "connected" | "ready" | "offline";

/** The part of the browser `WebSocket` the stream uses (tests pass a fake). */
export interface SocketLike {
  readyState: number;
  onopen: ((ev: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
  send(data: string): void;
  close(): void;
}

/** Timer functions (tests pass a fake clock). */
export interface Clock {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface EventStreamOptions {
  /** WebSocket URL, e.g. `ws://127.0.0.1:7777/api/v1/ws`. */
  url: string;
  /** Called with new events, deduplicated by sequence, in order, batched. */
  onEvents: (events: HxEvent[]) => void;
  onStatus?: (status: StreamStatus) => void;
  createSocket?: (url: string) => SocketLike;
  clock?: Clock;
  /** Last sequence already seen and trusted; the first subscribe replays after it. Default 0. */
  afterSequence?: number;
  /**
   * Sequence saved by an earlier page load (not trusted: the server may serve another
   * store now). The first subscribe asks for the events after `resumeSequence - 1`; event
   * `resumeSequence` must come back before `ready` (it is not delivered again), else the
   * stream reconnects from 0. Ignored when `afterSequence` is given.
   */
  resumeSequence?: number;
  /** Called with the last delivered sequence after `ready` and after each batch. */
  onSequence?: (sequence: number) => void;
  /**
   * Looks up the server's newest event sequence. Given, a stream with nothing to resume
   * (no `afterSequence`, no `resumeSequence`, or a stored sequence the server lacks)
   * subscribes after it instead of after 0, so it does not replay the whole log. A
   * failure, an invalid answer, or no answer within `HEAD_TIMEOUT_MS` means 0.
   */
  head?: () => Promise<number | null>;
  /** Refresh reads taken before an accepted head: events up to it will not replay. */
  onHead?: () => void;
}

export interface EventStreamHookOptions {
  url?: string;
  createSocket?: (url: string) => SocketLike;
  clock?: Clock;
  /** Where the last sequence is kept; default `sessionStorage`, `null` keeps nothing. */
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  /** Newest-sequence lookup; default `fetchLastSequence` (`GET /hosts`), `null` none (start at 0). */
  head?: (() => Promise<number | null>) | null;
}

/** Reconnect delays in ms: 3, 4, 8, then 16 s for every later attempt. */
export const BACKOFF_MS: readonly number[] = [3_000, 4_000, 8_000, 16_000];
/** A connection open this long resets the backoff to its first step. */
export const STABLE_RESET_MS = 30_000;
/** Live events that arrive within this window are delivered as one batch. */
export const FLUSH_MS = 250;
/** A newest-sequence lookup slower than this is dropped; the stream replays from 0. */
export const HEAD_TIMEOUT_MS = 5_000;

/** `sessionStorage` key for the last delivered event sequence (per tab and origin). */
export const SEQUENCE_KEY = "hx-ws-sequence";

/** The stored sequence, or 0 when it is missing, not a positive integer, or unreadable. */
export function readSequence(storage: Pick<Storage, "getItem"> | null): number {
  try {
    const raw = storage?.getItem(SEQUENCE_KEY) ?? "";
    const value = /^[0-9]+$/.test(raw) ? Number(raw) : 0;
    return Number.isSafeInteger(value) ? value : 0;
  } catch {
    return 0;
  }
}

/** Save the sequence; a full or disabled storage only means the next load replays more. */
export function writeSequence(storage: Pick<Storage, "setItem"> | null, sequence: number): void {
  try {
    storage?.setItem(SEQUENCE_KEY, String(sequence));
  } catch {
    // ignore: the next page load replays from an older sequence
  }
}

function defaultStorage(): Pick<Storage, "getItem" | "setItem"> | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

/** Run families whose next key segment is the project. */
const BY_PROJECT = new Set(["task", "leaderboard", "views/query", "sweeps"]);

/** Event type the hub emits after mirroring a remote run's event (phase 2 contract 1.5). */
export const MIRROR_RUN_UPDATED = "mirror.run_updated";

const CONNECTING = 0;

const realClock: Clock = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Delay before reconnect attempt `attempt` (0-based). */
export function backoffDelay(attempt: number): number {
  const index = Math.min(Math.max(attempt, 0), BACKOFF_MS.length - 1);
  return BACKOFF_MS[index] ?? 16_000;
}

/**
 * Query keys to invalidate for one event.
 *
 * - `run.*`: `RUN_EVENT_INVALIDATES`, narrowed to the event's run and project.
 * - `mirror.run_updated` (a remote run changed): `REMOTE_RUN_INVALIDATES`, narrowed the
 *   same way, so it also refreshes the hosts list.
 * - `host.*`: `HOST_EVENT_INVALIDATES` as is (a host change touches all its runs).
 * - anything else: nothing.
 */
export function keysForEvent(event: HxEvent): QueryKey[] {
  if (event.type.startsWith("host.")) return HOST_EVENT_INVALIDATES.map((family) => [...family]);
  if (event.type === MIRROR_RUN_UPDATED) return narrow(REMOTE_RUN_INVALIDATES, event);
  if (event.type.startsWith("run.")) return narrow(RUN_EVENT_INVALIDATES, event);
  return [];
}

/**
 * Narrow key families to one run event where the key allows: `["run", runId]` (prefix
 * match, so it covers the run's metrics, logs, predictions and traces), and
 * `["task" | "leaderboard" | "sweeps", project]`, `["views", "query", project]`.
 */
function narrow(families: readonly QueryKey[], event: HxEvent): QueryKey[] {
  const keys: QueryKey[] = [];
  for (const family of families) {
    const id = family.join("/");
    if (id === "run") {
      if (event.run_id) keys.push([...family, event.run_id]);
    } else if (event.project && BY_PROJECT.has(id)) {
      keys.push([...family, event.project]);
    } else {
      keys.push([...family]);
    }
  }
  return keys;
}

/** Union of `keysForEvent` over a batch, without duplicates, in first-seen order. */
export function keysForEvents(events: readonly HxEvent[]): QueryKey[] {
  const seen = new Set<string>();
  const keys: QueryKey[] = [];
  for (const event of events) {
    for (const key of keysForEvent(event)) {
      const id = JSON.stringify(key);
      if (seen.has(id)) continue;
      seen.add(id);
      keys.push(key);
    }
  }
  return keys;
}

/**
 * Invalidate every query a batch of events may have changed (active ones refetch).
 *
 * One `invalidateQueries` call for the whole batch: a query that two keys match (e.g. a
 * run page under `["run", id]` and `["run"]`) refetches once, not once per key with the
 * second call aborting the first.
 */
export function invalidateForEvents(client: QueryClient, events: readonly HxEvent[]): void {
  const keys = keysForEvents(events);
  if (keys.length === 0) return;
  void client.invalidateQueries({ predicate: (query) => keys.some((key) => partialMatchKey(query.queryKey, key)) });
}

/** Connection supervisor for `/api/v1/ws` (one per app). */
export class EventStream {
  private readonly options: EventStreamOptions;
  private readonly clock: Clock;
  private readonly createSocket: (url: string) => SocketLike;
  private socket: SocketLike | null = null;
  private lastSequence: number;
  /** A stored sequence still to be confirmed by the server (see `resumeSequence`). */
  private anchor: number | null = null;
  private attempt = 0;
  private ready = false;
  private running = false;
  private pending: HxEvent[] = [];
  private reconnectTimer: unknown = null;
  private stableTimer: unknown = null;
  private flushTimer: unknown = null;
  /** Subscribe after the server's newest sequence (looked up first), not after 0. */
  private needHead: boolean;
  private headTimer: unknown = null;
  /** Bumped by each lookup and by `stop()`: an answer for an older token is ignored. */
  private headToken = 0;

  constructor(options: EventStreamOptions) {
    this.options = options;
    this.clock = options.clock ?? realClock;
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    const resume = options.resumeSequence ?? 0;
    if (options.afterSequence === undefined && resume > 0) {
      this.lastSequence = resume - 1;
      this.anchor = resume;
    } else {
      this.lastSequence = options.afterSequence ?? 0;
    }
    this.needHead = options.head !== undefined && options.afterSequence === undefined && resume <= 0;
  }

  /** Highest event sequence seen so far. */
  get sequence(): number {
    return this.lastSequence;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.connect();
  }

  stop(): void {
    this.running = false;
    this.cancel(this.reconnectTimer);
    this.cancel(this.stableTimer);
    this.cancel(this.flushTimer);
    this.cancel(this.headTimer);
    this.reconnectTimer = null;
    this.stableTimer = null;
    this.flushTimer = null;
    this.headTimer = null;
    this.headToken += 1;
    this.pending = [];
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    if (socket.readyState === CONNECTING) {
      // close() on a CONNECTING socket makes browsers log an error; close once it opens.
      socket.onopen = () => socket.close();
    } else {
      socket.onopen = null;
      socket.close();
    }
  }

  private cancel(handle: unknown): void {
    if (handle !== null) this.clock.clearTimeout(handle);
  }

  private setStatus(status: StreamStatus): void {
    this.options.onStatus?.(status);
  }

  private connect(): void {
    this.ready = false;
    this.setStatus("connecting");
    if (this.needHead && this.options.head) {
      this.lookupHead(this.options.head);
      return;
    }
    this.open();
  }

  /** Ask for the newest sequence, then open the socket after it (0 on failure or timeout). */
  private lookupHead(head: () => Promise<number | null>): void {
    const token = ++this.headToken;
    const finish = (sequence: number | null): void => {
      if (token !== this.headToken || !this.running) return;
      this.headToken += 1;
      this.cancel(this.headTimer);
      this.headTimer = null;
      this.needHead = false;
      this.lastSequence = sequence ?? 0;
      if (sequence !== null) this.options.onHead?.();
      this.open();
    };
    this.headTimer = this.clock.setTimeout(() => finish(null), HEAD_TIMEOUT_MS);
    let answer: Promise<number | null>;
    try {
      answer = head();
    } catch {
      answer = Promise.resolve(null);
    }
    answer.then(
      (n) => finish(typeof n === "number" && Number.isSafeInteger(n) && n >= 0 ? n : null),
      () => finish(null),
    );
  }

  private open(): void {
    let socket: SocketLike;
    try {
      socket = this.createSocket(this.options.url);
    } catch {
      this.setStatus("offline");
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      if (socket !== this.socket) return;
      this.setStatus("connected");
      socket.send(JSON.stringify({ type: "subscribe", after_sequence: this.lastSequence }));
      this.stableTimer = this.clock.setTimeout(() => {
        this.stableTimer = null;
        this.attempt = 0;
      }, STABLE_RESET_MS);
    };
    socket.onmessage = (ev) => {
      if (socket === this.socket) this.handle(ev.data);
    };
    socket.onerror = () => {
      // A close event always follows an error; reconnecting happens there.
    };
    socket.onclose = () => {
      if (socket === this.socket) this.handleClose();
    };
  }

  private handleClose(): void {
    this.socket = null;
    this.ready = false;
    this.cancel(this.stableTimer);
    this.stableTimer = null;
    if (!this.running) return;
    this.setStatus("offline");
    this.scheduleReconnect();
  }

  /**
   * The server lacks the stored sequence (another or a reset store): start over from its
   * newest sequence (with a `head` lookup), else from 0.
   */
  private restartFromZero(): void {
    this.anchor = null;
    this.lastSequence = 0;
    this.needHead = this.options.head !== undefined;
    this.pending = [];
    this.cancel(this.stableTimer);
    this.stableTimer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    }
    this.connect();
  }

  private scheduleReconnect(): void {
    const delay = backoffDelay(this.attempt);
    this.attempt += 1;
    this.reconnectTimer = this.clock.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.running) this.connect();
    }, delay);
  }

  private handle(data: unknown): void {
    let message: unknown;
    try {
      message = JSON.parse(String(data));
    } catch {
      return;
    }
    if (typeof message !== "object" || message === null) return;
    const msg = message as { type?: unknown; event?: Partial<HxEvent>; last_sequence?: unknown };
    if (msg.type === "event") {
      this.receive(msg.event);
    } else if (msg.type === "ready") {
      if (this.anchor !== null) {
        this.restartFromZero();
        return;
      }
      const last = typeof msg.last_sequence === "number" ? msg.last_sequence : this.lastSequence;
      this.markReady(last);
    } else if (msg.type === "error") {
      // The subscribe itself was rejected; retrying would repeat the same error.
      this.stop();
      this.setStatus("offline");
    }
  }

  private receive(event: Partial<HxEvent> | undefined): void {
    if (!event || typeof event.sequence !== "number" || typeof event.type !== "string") return;
    if (this.anchor !== null && event.sequence > this.lastSequence) {
      // First event after a resume: the stored one (seen on an earlier page) confirms it;
      // a higher one means it is gone, but every later event still arrives.
      const anchor = this.anchor;
      this.anchor = null;
      if (event.sequence === anchor) {
        this.lastSequence = anchor;
        return;
      }
    }
    if (event.sequence <= this.lastSequence) return;
    this.lastSequence = event.sequence;
    this.pending.push(event as HxEvent);
    if (this.ready && this.flushTimer === null) {
      this.flushTimer = this.clock.setTimeout(() => {
        this.flushTimer = null;
        this.flush();
        this.options.onSequence?.(this.lastSequence);
      }, FLUSH_MS);
    }
  }

  private markReady(lastSequence: number): void {
    this.ready = true;
    this.lastSequence = Math.max(this.lastSequence, lastSequence);
    this.setStatus("ready");
    this.flush();
    this.options.onSequence?.(this.lastSequence);
  }

  private flush(): void {
    if (this.pending.length === 0) return;
    const batch = this.pending;
    this.pending = [];
    this.options.onEvents(batch);
  }
}

/**
 * Subscribe to live events for the app's lifetime and invalidate affected queries.
 * While the stream is offline, a window focus refetches every query instead.
 *
 * Call once (through `LiveUpdates`). Options are read on mount only (tests pass fakes).
 */
export function useEventStream(options: EventStreamHookOptions = {}): StreamStatus {
  const client = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const initial = useRef(options);
  useEffect(() => {
    const { url, createSocket, clock } = initial.current;
    const storage = initial.current.storage === undefined ? defaultStorage() : initial.current.storage;
    const head = initial.current.head === undefined ? () => fetchLastSequence(client) : initial.current.head;
    const stream = new EventStream({
      url: url ?? wsUrl(),
      onEvents: (events) => {
        noteLostReasons(events);
        invalidateForEvents(client, events);
      },
      onStatus: setStatus,
      onSequence: (sequence) => writeSequence(storage, sequence),
      resumeSequence: readSequence(storage),
      head: head ?? undefined,
      onHead: () => {
        // A page can finish its first read before /hosts chooses the head. Cancel
        // even initial reads still in flight, then refresh after that boundary;
        // otherwise a skipped event can leave the page stale until another event.
        // As with replayed events, leave the view editor's source alone.
        const keys = [...RUN_EVENT_INVALIDATES, ...HOST_EVENT_INVALIDATES];
        const filters = {
          predicate: (query: { queryKey: QueryKey }) => keys.some((key) => partialMatchKey(query.queryKey, key)),
        };
        void client.cancelQueries(filters).then(() => client.invalidateQueries(filters));
      },
      createSocket,
      clock,
    });
    stream.start();
    return () => stream.stop();
  }, [client]);
  // Queries do not refetch on focus while events keep them fresh; with the stream
  // offline (perhaps for good, after a server error) a focus refetches everything.
  useEffect(() => {
    if (status !== "offline") return;
    return focusManager.subscribe((focused) => {
      if (focused) void client.invalidateQueries();
    });
  }, [client, status]);
  return status;
}

/** Live-update stream status for the shell; `ready` outside `LiveUpdates`. */
export const StreamStatusContext = createContext<StreamStatus>("ready");

/** Status of the live-update stream (`ready` when screens are live). */
export function useStreamStatus(): StreamStatus {
  return useContext(StreamStatusContext);
}

export interface LiveUpdatesProps {
  children?: ReactNode;
  /** Test fakes for the stream (read on mount only). */
  options?: EventStreamHookOptions;
}

/**
 * Keeps the app's queries live and gives `children` the stream status
 * (`useStreamStatus`). Render once inside the `QueryClientProvider`, around the app.
 */
export function LiveUpdates({ children, options }: LiveUpdatesProps) {
  const status = useEventStream(options);
  return createElement(StreamStatusContext.Provider, { value: status }, children);
}
