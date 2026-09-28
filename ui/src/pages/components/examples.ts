/** Pure helpers for the two-run Examples page (spec 8.3.4 and 8.5). */
import { firstClause, fmtDelta, fmtP, fmtSigned, shortId } from "./format";
import type { ExampleDiff, RunRecord } from "./types";

function logFactorials(n: number): number[] {
  const out = [0];
  for (let k = 1; k <= n; k++) out.push((out[k - 1] ?? 0) + Math.log(k));
  return out;
}

/** Binomial(n, 1/2) probabilities for k = 0..n, computed in log space. */
export function binomPmf(n: number): number[] {
  if (!Number.isInteger(n) || n < 0) {
    throw new RangeError(`n must be a non-negative integer, got ${n}`);
  }
  const lf = logFactorials(n);
  const top = lf[n] ?? 0;
  return Array.from({ length: n + 1 }, (_, k) =>
    Math.exp(top - (lf[k] ?? 0) - (lf[n - k] ?? 0) - n * Math.LN2),
  );
}

/** Exact two-sided sign test on the discordant examples; 1 when none changed. */
export function signTestP(fixed: number, broken: number): number {
  const n = fixed + broken;
  if (n === 0) return 1;
  const pmf = binomPmf(n);
  const lo = Math.min(fixed, broken);
  let tail = 0;
  for (let k = 0; k <= lo; k++) tail += pmf[k] ?? 0;
  return Math.min(1, 2 * tail);
}

export type Outcome = "fixed" | "broken" | "both_fail" | "both_pass";

export interface Segment {
  outcome: Outcome;
  count: number;
  ids: string[];
  label: string;
}

/** Outcome groups in strip order; only fixed and broken ids are known. */
export function stripSegments(diff: ExampleDiff): Segment[] {
  return [
    { outcome: "fixed", count: diff.fixed.length, ids: diff.fixed, label: `${diff.fixed.length} fixed` },
    { outcome: "broken", count: diff.broken.length, ids: diff.broken, label: `${diff.broken.length} broken` },
    { outcome: "both_fail", count: diff.both_fail, ids: [], label: `${diff.both_fail} both wrong` },
    { outcome: "both_pass", count: diff.both_pass, ids: [], label: `${diff.both_pass} both right` },
  ];
}

/** Examples scored in both runs. */
export function exampleTotal(diff: ExampleDiff): number {
  return diff.fixed.length + diff.broken.length + diff.both_fail + diff.both_pass;
}

/** Short labels for runs A and B; equal labels get the run's short id. */
export function pairLabels(a: RunRecord, b: RunRecord): [string, string] {
  const la = firstClause(a.hypothesis, `run ${shortId(a.run_id)}`);
  const lb = firstClause(b.hypothesis, `run ${shortId(b.run_id)}`);
  if (la !== lb) return [la, lb];
  return [`${la} ${shortId(a.run_id)}`, `${lb} ${shortId(b.run_id)}`];
}

/** `B fixes 9, breaks 3 vs A, p = 0.15`. */
export function examplesHeadline(labelA: string, labelB: string, diff: ExampleDiff): string {
  const p = signTestP(diff.fixed.length, diff.broken.length);
  return `${labelB} fixes ${diff.fixed.length}, breaks ${diff.broken.length} vs ${labelA}, ${fmtP(p)}`;
}

/** `n = 180`, `net +6`, `Δ +0.0333` (the change in pass rate). */
export function examplesMeta(diff: ExampleDiff): string[] {
  const n = exampleTotal(diff);
  if (n === 0) return ["n = 0"];
  const net = diff.fixed.length - diff.broken.length;
  return [`n = ${n}`, `net ${fmtSigned(net)}`, `Δ ${fmtDelta(net / n)}`];
}
