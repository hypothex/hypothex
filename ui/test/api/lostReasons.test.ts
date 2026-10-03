import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { type Clock, type SocketLike, useEventStream } from "../../src/api/events";
import { clearLostReasons, lostReasonFor, lostReasonOf, noteLostReasons, useLostReason } from "../../src/api/lostReasons";
import type { HxEvent } from "../../src/api/models";

const NODE_FAIL = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";

function ev(sequence: number, type: string, payload: Record<string, unknown>, run_id: string | null = "r1"): HxEvent {
  return { sequence, type, project: "toy", run_id, payload, created_at: "2026-10-03T02:14:37Z" };
}

afterEach(clearLostReasons);

describe("lost reasons", () => {
  test("lostReasonOf reads run.lost and a mirrored run.lost, nothing else", () => {
    expect(lostReasonOf(ev(1, "run.lost", { reason: NODE_FAIL, slurm_job_id: "4471023" }))).toBe(NODE_FAIL);
    expect(
      lostReasonOf(ev(2, "mirror.run_updated", { original_type: "run.lost", status: "lost", reason: ` ${NODE_FAIL} ` })),
    ).toBe(NODE_FAIL);
    // a mirrored event about something else, a reasonless one, a blank one, no run id
    expect(lostReasonOf(ev(3, "mirror.run_updated", { original_type: "run.finished", reason: "x" }))).toBeNull();
    expect(lostReasonOf(ev(4, "mirror.run_updated", { original_type: "run.lost", status: "lost" }))).toBeNull();
    expect(lostReasonOf(ev(5, "run.lost", { reason: "   " }))).toBeNull();
    expect(lostReasonOf(ev(6, "run.lost", { reason: 7 }))).toBeNull();
    expect(lostReasonOf(ev(7, "run.lost", { reason: NODE_FAIL }, null))).toBeNull();
    expect(lostReasonOf(ev(8, "run.failed", { reason: NODE_FAIL }))).toBeNull();
  });

  test("noteLostReasons keeps one reason per run and useLostReason follows it", () => {
    const { result } = renderHook(() => useLostReason("r1"));
    expect(result.current).toBeNull();
    act(() => noteLostReasons([ev(1, "run.started", {}), ev(2, "run.lost", { reason: NODE_FAIL })]));
    expect(result.current).toBe(NODE_FAIL);
    expect(lostReasonFor("r2")).toBeNull();
    // a later event without a reason does not erase it
    act(() => noteLostReasons([ev(3, "mirror.run_updated", { original_type: "run.lost" })]));
    expect(result.current).toBe(NODE_FAIL);
  });

  test("the app's event stream records the reason of a mirrored run.lost", () => {
    const sockets: StubSocket[] = [];
    const timers: (() => void)[] = [];
    const clock: Clock = {
      setTimeout: (fn) => timers.push(fn),
      clearTimeout: () => {},
    };
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    const { unmount } = renderHook(
      () =>
        useEventStream({
          url: "ws://127.0.0.1:1/api/v1/ws",
          clock,
          storage: null,
          createSocket: () => {
            const socket = new StubSocket();
            sockets.push(socket);
            return socket;
          },
        }),
      { wrapper },
    );
    const socket = sockets[0];
    if (!socket) throw new Error("the hook opened no socket");
    act(() => {
      socket.readyState = 1;
      socket.onopen?.(new Event("open"));
      socket.push({ type: "ready", last_sequence: 0 });
      socket.push({
        type: "event",
        event: ev(1, "mirror.run_updated", { original_type: "run.lost", status: "lost", reason: NODE_FAIL }, "r9"),
      });
      // the stream delivers live events in batches after FLUSH_MS: run the pending timers
      for (const fire of timers.splice(0)) fire();
    });
    expect(lostReasonFor("r9")).toBe(NODE_FAIL);
    unmount();
  });
});

/** The part of a WebSocket the stream uses; `push` delivers one server message. */
class StubSocket implements SocketLike {
  readyState = 0;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  send(): void {}
  close(): void {
    this.readyState = 3;
  }
  push(message: unknown): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(message) }));
  }
}
