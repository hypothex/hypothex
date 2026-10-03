/**
 * Metric value formatting driven by panel meta.
 *
 * The server may send `meta.unit` (e.g. `ms`, `$`, `%`) and `meta.value_format`: one of the
 * backend hints `fraction` (4 decimals, absolute deltas), `number` (3 significant figures,
 * absolute deltas) or `percent_delta` (3 significant figures, deltas as a relative change),
 * or else a d3-format specifier (e.g. `.3~r`, `.1%`, `,.0f`). Without them the rule is: values
 * above 1 in magnitude, or with a unit, get 3 significant figures and the unit; values in
 * [-1, 1] keep 4 decimals (scores such as accuracy). Differences of latency-like metrics
 * read as a relative change (`+27%`), since "45 ms slower" depends on the baseline.
 */
import { format } from "d3-format";
import { MINUS, f3, f4, signed } from "./Scale";

/** Formatting for one metric column. */
export interface ValueFormatter {
  /** The unit, `""` when none. */
  unit: string;
  /** A value without its unit: `166`, `0.9222`. */
  num: (v: number) => string;
  /** A value with its unit: `166 ms`, `$0.55`, `0.9222`. */
  value: (v: number) => string;
  /** An interval end (shorter than `num` for scores): `0.874`, `164`. */
  bound: (v: number) => string;
  /** A spread (std) without unit: `2.80`, `0.0064`. */
  spread: (v: number) => string;
  /** `v - ref` as shown in a vs-best column: `−0.037`, `+27%`, `+45.0 ms`. */
  delta: (v: number, ref: number) => string;
}

const TIME_UNITS = new Set(["ns", "us", "µs", "ms", "s", "sec", "min", "h"]);
const LATENCY_KEY = /latenc|duration|elapsed|(^|[/_ ])(p50|p9\d|time|ms)($|[/_ ])/i;

/** True when differences of this metric are best read as a relative change. */
export function isLatencyLike(unit: string, key = ""): boolean {
  return TIME_UNITS.has(unit.trim().toLowerCase()) || LATENCY_KEY.test(key);
}

/** Attach a unit: `$` and `£` lead, `%` hugs the number, others follow after a space. */
export function withUnit(text: string, unit: string): string {
  if (!unit) return text;
  if (unit === "$" || unit === "£" || unit === "€") {
    return text.startsWith(MINUS) ? `${MINUS}${unit}${text.slice(1)}` : `${unit}${text}`;
  }
  if (unit === "%") return `${text}%`;
  return `${text} ${unit}`;
}

const minus = (s: string): string => s.replace("-", MINUS);
const sig3 = format(",.3r");
const sig3Trim = format(",.3~r");

/** 3 significant figures with a real minus: `166`, `2.80`, `1,230`. */
export function fmtSig3(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (v === 0) return "0";
  return minus(sig3(v));
}

/** 3 significant figures, trailing zeros dropped: `3`, `1.3`, `45.1`. */
export function fmtSig3Trim(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  return v === 0 ? "0" : minus(sig3Trim(v));
}

// Plain formatters shared by panels and pages (one definition each). ---------------------

/**
 * Format a number tersely.
 *
 * Integers are grouped (`12,000`), values in [-1, 1] get three decimals (`0.663`), values
 * below 1000 get three significant digits (`12.3`), larger values are rounded and grouped.
 */
export function fmtNum(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  const a = Math.abs(v);
  let s: string;
  if (Number.isInteger(a)) s = a.toLocaleString("en-US");
  else if (a < 0.001) s = String(Number(a.toPrecision(2)));
  else if (a <= 1) s = a.toFixed(3);
  else if (a < 1000) s = String(Number(a.toPrecision(3)));
  else s = Math.round(a).toLocaleString("en-US");
  return v < 0 ? MINUS + s : s;
}

/** A signed number (`fmtNum` digits): `+6`, `−2`, `+0.025`, `0`. */
export function fmtSigned(v: number): string {
  const s = fmtNum(v);
  return v > 0 && Number(s.replace(/,/g, "")) !== 0 ? `+${s}` : s;
}

/** A wall-clock duration: `0.8 s`, `2m 5s`, `5h 40m`; `—` when missing. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

/** The random tail of a run id: `…-toy-test-6f71` → `6f71`. */
export function shortId(runId: string): string {
  return runId.split("-").pop() || runId;
}

/**
 * An axis title: `label, unit, log`. The unit is left out when the label already ends
 * with it (`latency_ms`, `latency/ms`) or when the ticks carry it (`unitOnTicks`).
 */
export function axisTitle(
  label: string,
  unit: string,
  { log = false, unitOnTicks = false }: { log?: boolean; unitOnTicks?: boolean } = {},
): string {
  const named = unit !== "" && (label.endsWith(`_${unit}`) || label.endsWith(`/${unit}`));
  return [label, named || unitOnTicks ? "" : unit, log ? "log" : ""].filter(Boolean).join(", ");
}

/** Parse a d3-format specifier; null when missing or invalid. */
export function parseFormat(spec: unknown): ((v: number) => string) | null {
  if (typeof spec !== "string" || spec === "") return null;
  try {
    const f = format(spec);
    return (v) => minus(f(v));
  } catch {
    return null;
  }
}

function signedPct(rel: number): string {
  const pct = Math.abs(rel * 100);
  const digits = pct < 10 && pct !== 0 ? 1 : 0;
  const s = pct.toFixed(digits);
  if (Number(s) === 0) return "0%";
  return `${rel < 0 ? MINUS : "+"}${s}%`;
}

function signedWith(num: (v: number) => string, d: number, unit: string): string {
  const s = num(Math.abs(d));
  if (Number(s.replace(/[^0-9.]/g, "")) === 0) return withUnit(s, unit);
  return `${d < 0 ? MINUS : "+"}${withUnit(s, unit)}`;
}

/**
 * Build the formatter for one metric column.
 *
 * Parameters
 * ----------
 * meta : object | undefined
 *     Panel meta; reads `unit` and `value_format`.
 * values : number[]
 *     The column's values, to choose between the score and magnitude rules.
 * key : string
 *     The metric key, e.g. `latency/p95`, to spot latency-like metrics.
 *
 * Returns
 * -------
 * ValueFormatter
 *
 * Examples
 * --------
 * >>> valueFormatter({ unit: "ms" }, [165.62], "latency/p95").delta(210.58, 165.62)
 * "+27%"
 */
export function valueFormatter(
  meta: Record<string, unknown> | undefined,
  values: number[],
  key = "",
): ValueFormatter {
  const unit = typeof meta?.unit === "string" ? meta.unit.trim() : "";
  const hint = meta?.value_format;
  const known = hint === "fraction" || hint === "number" || hint === "percent_delta";
  const custom = known ? null : parseFormat(hint);
  const big = values.some((v) => Number.isFinite(v) && Math.abs(v) > 1);
  const latency = hint === "percent_delta" || (!known && isLatencyLike(unit, key));
  const scoreLike = hint === "fraction" ? !unit : !known && !custom && !unit && !big;
  const num = custom ?? (scoreLike ? f4 : fmtSig3);
  return {
    unit,
    num,
    value: (v) => withUnit(num(v), unit),
    bound: scoreLike ? f3 : num,
    spread: custom ?? (scoreLike ? f4 : fmtSig3),
    delta: (v, ref) => {
      const d = v - ref;
      if (latency && ref !== 0) return signedPct(d / Math.abs(ref));
      if (scoreLike) return signed(d, 3);
      return signedWith(custom ?? fmtSig3Trim, d, unit);
    },
  };
}
