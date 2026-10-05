/** Pure formatting helpers shared by the pages. Times are shown in UTC. */
import { format } from "d3-format";
import { MINUS, fmtP as pDigits } from "../../charts/Scale";
import { shortId, withUnit } from "../../charts/valueFormat";

// Shared with the panels: one definition each, in charts/valueFormat.
export { fmtDuration, fmtSigned, shortId } from "../../charts/valueFormat";
import type { RunRecord } from "./types";

/** Shown for a missing value (the same glyph as the panels). */
export const DASH = "—";
export { MINUS };

const sig3 = format(".3~g");
const si3 = format(".3~s");

/** True for finite numbers. */
export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Parse an ISO time; trims sub-millisecond digits first (Python writes microseconds). */
export function parseTime(iso: string): number {
  return Date.parse(iso.replace(/(\.\d{3})\d+/, "$1"));
}

function minus(text: string): string {
  return text.replace("-", MINUS);
}

/** A metric value: 4 decimals in [-1, 1], 3 significant digits below 1000, else SI. */
export function fmtScore(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  if (a <= 1) return minus(v.toFixed(4));
  if (a < 1000) return minus(sig3(v));
  return minus(si3(v));
}

/**
 * A metric value with its unit: `166 ms`, `$0.55`, `1.23k tokens`; `fmtScore` without a
 * unit. Dollars from 0.01 to 100 keep cents, like the backend's `fmt_metric`.
 */
export function fmtScoreUnit(v: number | null | undefined, unit = ""): string {
  if (!isNum(v)) return DASH;
  if (!unit) return fmtScore(v);
  const a = Math.abs(v);
  const num = unit === "$" && a >= 0.01 && a < 100 ? v.toFixed(2) : a < 1000 ? sig3(v) : si3(v);
  return withUnit(minus(num), unit);
}

/** A signed metric difference, e.g. `+0.0333`. */
export function fmtDelta(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  const sign = v > 0 ? "+" : v < 0 ? MINUS : "";
  return `${sign}${fmtScore(Math.abs(v))}`;
}

/** An interval `lo–hi`; 3 decimals when both ends are fractions. */
export function fmtInterval(lo: number, hi: number): string {
  if (Math.abs(lo) <= 1 && Math.abs(hi) <= 1) {
    return `${minus(lo.toFixed(3))}–${minus(hi.toFixed(3))}`;
  }
  return `${fmtScore(lo)}–${fmtScore(hi)}`;
}

/** A p-value with its name: `p = 0.15`, `p = 0.002`, or `p < 0.001` (digits from `charts/Scale`). */
export function fmtP(p: number | null | undefined): string {
  if (!isNum(p)) return DASH;
  const digits = pDigits(p);
  return digits.startsWith("<") ? `p ${digits}` : `p = ${digits}`;
}

/** Seconds a run has taken (so far, while it runs); null before it starts. */
export function runSeconds(record: RunRecord, now: number = Date.now()): number | null {
  if (!record.started_at) return null;
  const start = parseTime(record.started_at);
  const end = record.ended_at ? parseTime(record.ended_at) : now;
  if (!isNum(start) || !isNum(end)) return null;
  return Math.max(0, (end - start) / 1000);
}

function utcParts(iso: string): Date | null {
  const t = parseTime(iso);
  return Number.isNaN(t) ? null : new Date(t);
}

const pad = (n: number): string => String(n).padStart(2, "0");

/** `21:03` (UTC). */
export function fmtClock(iso: string): string {
  const d = utcParts(iso);
  return d ? `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}` : DASH;
}

/** `21:03:06 UTC`. */
export function fmtTime(iso: string): string {
  const d = utcParts(iso);
  return d
    ? `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`
    : DASH;
}

/** `2026-09-26 21:03` (UTC). */
export function fmtDate(iso: string): string {
  const d = utcParts(iso);
  if (!d) return DASH;
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${fmtClock(iso)}`;
}

/** A byte size with SI units: `18.5 KB`. */
export function fmtBytes(n: number): string {
  if (n < 1e3) return `${n} B`;
  if (n < 1e6) return `${(n / 1e3).toFixed(1)} KB`;
  if (n < 1e9) return `${(n / 1e6).toFixed(1)} MB`;
  return `${(n / 1e9).toFixed(1)} GB`;
}

/** Dollars: 3 decimals below $0.10, else 2. */
export function fmtUsd(v: number): string {
  return v < 0.1 ? `$${v.toFixed(3)}` : `$${v.toFixed(2)}`;
}

/** A count: exact below 1000, else SI (`4.5k`). */
export function fmtCount(n: number): string {
  return n < 1000 ? String(Math.round(n)) : si3(n);
}

/** The first 8 hex digits of a `sha256:`/`xxh3:` hash. */
export function shortHash(hash: string): string {
  return hash.replace(/^[a-z0-9]+:/, "").slice(0, 8);
}

const CLAUSE = /[,;(]|[.:](?:\s|$)|\s(?:should|because|so that|will)\s/i;

/** A short label from a hypothesis: text before the first clause break. */
export function firstClause(text: string, fallback: string, max = 40): string {
  const t = text.trim();
  if (!t) return fallback;
  const m = CLAUSE.exec(t);
  const head = (m ? t.slice(0, m.index) : t).trim() || t;
  return head.length > max ? `${head.slice(0, max - 1).trimEnd()}…` : head;
}

/** Split `host:/abs/path`; a bare path is on `local`. */
export function splitHostPath(value: string): { host: string; path: string } {
  const m = /^([A-Za-z0-9_.-]+):(\/.*)$/.exec(value);
  return m ? { host: m[1] ?? "local", path: m[2] ?? value } : { host: "local", path: value };
}

/** `path` for local files, `host:path` elsewhere. */
export function displayPath(host: string, path: string): string {
  return host === "local" ? path : `${host}:${path}`;
}

/** `path` relative to `base`, `"."` for `base` itself, or null when outside it. */
export function relativeTo(path: string, base: string): string | null {
  const b = base.replace(/\/+$/, "");
  if (path === b) return ".";
  return path.startsWith(`${b}/`) ? path.slice(b.length + 1) : null;
}

/** The last `keep` segments of a long path, prefixed with `…/`. */
export function tailPath(path: string, keep = 3): string {
  const parts = path.split("/").filter(Boolean);
  return parts.length <= keep ? path : `…/${parts.slice(-keep).join("/")}`;
}

const SAFE = /^[A-Za-z0-9_\-+=/.,:@%{}]+$/;

/** Join argv for display, single-quoting arguments a shell would split or expand. */
export function shellJoin(argv: string[]): string {
  return argv
    .map((a) => (a === "" ? "''" : SAFE.test(a) ? a : `'${a.replace(/'/g, `'"'"'`)}'`))
    .join(" ");
}

/** Any JSON value as short text (80 characters at most). */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return DASH;
  const text = typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v) : String(v);
  return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

/** `accuracy/value` → `accuracy`. */
export function primaryMetricName(primary: string): string {
  return primary.split("/")[0] ?? primary;
}

/** Launchers named `agent…` are agents; everyone else is a human. */
export function isAgent(createdBy: string): boolean {
  return createdBy.startsWith("agent");
}

/** Distinguish queued configurations and repeat seeds without hiding their hypothesis. */
export function queueLabel(record: RunRecord): string {
  const params = Object.entries(record.params).map(([key, value]) => `${key}=${value}`).join(", ");
  return [firstClause(record.hypothesis, `run ${shortId(record.run_id)}`), params,
    record.seed === null ? "" : `seed ${record.seed}`].filter(Boolean).join(" · ");
}
