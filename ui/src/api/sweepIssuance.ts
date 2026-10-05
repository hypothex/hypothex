import type { SweepIssuance } from "./models";

/** Preparing is observable but not accepted or cancellable. */
export function issuanceActive(issuance: SweepIssuance | null | undefined): boolean {
  return issuance !== null && issuance !== undefined &&
    ["preparing", "queued", "issuing", "settling"].includes(issuance.state);
}

/** Poll through admission and issuance even when no member event has arrived yet. */
export function issuancePoll(issuance: SweepIssuance | null | undefined): number | false {
  return issuanceActive(issuance) ? 2000 : false;
}

/** Failed episodes may retain accepted members that have not reached the index yet. */
export function issuanceCancellable(issuance: SweepIssuance | null | undefined): boolean {
  if (!issuance || issuance.cancel_requested || issuance.reason === "cancelled") return false;
  return ["queued", "issuing", "settling", "incomplete", "interrupted"].includes(issuance.state);
}
