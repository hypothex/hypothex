import { expect, test } from "bun:test";
import { issuanceActive, issuanceCancellable, issuancePoll } from "../../src/api/sweepIssuance";
import { keysForEvent } from "../../src/api/events";
import type { HxEvent, SweepIssuance, SweepIssuanceState } from "../../src/api/models";
const make = (state: SweepIssuanceState): SweepIssuance => ({ state, episode: 1, revision: 1, planned: 4, accepted_at: null, updated_at: "now", cancel_requested: false, reason: null, error: null, resume: null });
test("incomplete or interrupted issuance can cancel accepted members not yet mirrored", () => {
  for (const state of ["incomplete", "interrupted"] as const) {
    expect(issuanceCancellable(make(state))).toBe(true);
    expect(issuanceCancellable({ ...make(state), cancel_requested: true })).toBe(false);
    expect(issuanceCancellable({ ...make(state), reason: "cancelled" })).toBe(false);
  }
  expect(issuanceCancellable(make("issued"))).toBe(false);
  expect(issuanceCancellable(null)).toBe(false);
  expect(issuanceCancellable(undefined)).toBe(false);
  expect(issuancePoll({ ...make("settling"), cancel_requested: true })).toBe(2000);
  expect(issuancePoll({ ...make("interrupted"), cancel_requested: true, reason: "cancelled" })).toBe(false);
});
test("issuance polls admission through settling, but never auto-resumes terminal or legacy state", () => {
  for (const state of ["preparing", "queued", "issuing", "settling"] as const) expect(issuancePoll(make(state))).toBe(2000);
  for (const state of ["issued", "incomplete", "interrupted"] as const) expect(issuancePoll(make(state))).toBe(false);
  expect(issuancePoll(null)).toBe(false);
  expect(issuancePoll(undefined)).toBe(false);
  expect(issuanceActive(make("preparing"))).toBe(true);
  expect(issuanceCancellable(make("preparing"))).toBe(false);
  expect(issuanceCancellable(make("queued"))).toBe(true);
  expect(issuanceCancellable({ ...make("issuing"), cancel_requested: true })).toBe(false);
});
test("sweep issuance event invalidates its summary and project list without a run id", () => {
  const event: HxEvent = { sequence: 1, created_at: "now", type: "sweep.issuance", project: "toy", run_id: null, payload: { project: "toy", sweep_id: "s-one", state: "incomplete" } };
  expect(keysForEvent(event)).toEqual([["sweeps", "toy", "detail", "s-one"], ["sweeps", "toy", "list"]]);
});

test("an incomplete issuance event cannot crash the update stream", () => {
  expect(keysForEvent({ type: "sweep.issuance", sequence: 2 } as HxEvent)).toEqual([]);
});
