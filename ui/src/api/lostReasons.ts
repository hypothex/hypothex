/**
 * Why runs were lost, read from the event stream (spec 5.6, 8A.8).
 *
 * The env server writes the cause of a lost run into its `run.lost` event
 * (`payload.reason`); the run detail has no field for it. A hub run's own `run.lost`
 * carries it; a remote run's arrives as `mirror.run_updated` with
 * `original_type: "run.lost"` and the same `reason`. `useEventStream` passes every batch to
 * `noteLostReasons`; the run page reads one run's reason with `useLostReason`. A tab that
 * resumed after the event never sees it, so callers fall back to neutral words.
 */
import { useSyncExternalStore } from "react";

import type { HxEvent } from "./models";

const reasons = new Map<string, string>();
const listeners = new Set<() => void>();

function changed(): void {
  for (const listener of listeners) listener();
}

/**
 * The reason a `run.lost` event (or a `mirror.run_updated` of one) gives, trimmed; null
 * for any other event, a missing or blank reason, or an event without a run id. For
 * `{type: "run.lost", payload: {reason: "SLURM ended job 7 with NODE_FAIL on n2; no exit record"}}`
 * it is that text.
 */
export function lostReasonOf(event: HxEvent): string | null {
  const payload = event.payload ?? {};
  const lost =
    event.type === "run.lost" || (event.type === "mirror.run_updated" && payload.original_type === "run.lost");
  if (!lost || event.run_id === null) return null;
  const reason = typeof payload.reason === "string" ? payload.reason.trim() : "";
  return reason === "" ? null : reason;
}

/** Remember the reason of every lost-run event in `events`; later reasonless events keep it. */
export function noteLostReasons(events: readonly HxEvent[]): void {
  let any = false;
  for (const event of events) {
    const reason = lostReasonOf(event);
    if (reason === null || event.run_id === null || reasons.get(event.run_id) === reason) continue;
    reasons.set(event.run_id, reason);
    any = true;
  }
  if (any) changed();
}

/** The reason seen for `runId`, or null. */
export function lostReasonFor(runId: string): string | null {
  return reasons.get(runId) ?? null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** `lostReasonFor(runId)`, re-rendering when a reason for any run arrives. */
export function useLostReason(runId: string): string | null {
  return useSyncExternalStore(
    subscribe,
    () => lostReasonFor(runId),
    () => null,
  );
}

/** Forget every reason (tests). */
export function clearLostReasons(): void {
  reasons.clear();
  changed();
}
