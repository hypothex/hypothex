/**
 * Time x axes for line charts (spec 4.2 "x axis: step | wall time | relative time"):
 * `clock` reads epoch seconds as local wall-clock time (`14:05`, `14:05:30`, `Oct 16`),
 * `duration` reads seconds since a start (`0`, `30s`, `2m`, `1.5h`, `0.5ms`). Ticks fall on
 * whole time units (1/2/5/10/15/30 s, 1/2/5/10/15/30 min, 1/2/3/6/12 h, days), local
 * midnight-aligned for clocks.
 */
import { niceStep, niceTicks } from "../lib/ticks";

/** Tick steps in seconds from 1 s to 12 h; longer spans step in nice numbers of days. */
const STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200] as const;
const DAY = 86400;
const MAX_TICKS = 1000;

/** Seconds to add to epoch seconds to get local time at `t` (e.g. 19800 for UTC+5:30). */
export function localOffset(t: number): number {
  return -new Date(t * 1000).getTimezoneOffset() * 60;
}

/**
 * Ticks inside `[x0, x1]` on whole time units, about `count` of them. `offset` shifts the
 * grid: seconds to add for local time, a number or a function of the time (`localOffset`,
 * so a span across a DST change keeps every tick on a whole local unit). Sub-second spans
 * fall back to decimal steps.
 *
 * Examples
 * --------
 * >>> timeTicks(0, 5400, 4)
 * [0, 1800, 3600, 5400]
 */
export function timeTicks(x0: number, x1: number, count: number, offset: number | ((t: number) => number) = 0): number[] {
  if (!Number.isFinite(x0) || !Number.isFinite(x1)) return [];
  const span = x1 - x0;
  if (!(span > 0)) return [x0];
  const raw = span / Math.max(1, count);
  if (raw < 1) {
    // decimal steps measured from a whole second, so epoch values keep their precision
    const base = Math.floor(x0);
    return niceTicks(x0 - base, x1 - base, count).map((v) => base + v);
  }
  const step = STEPS.find((s) => s >= raw * (1 - 1e-9)) ?? DAY * Math.max(1, Math.ceil(niceStep(span / DAY, count)));
  const off = typeof offset === "number" ? () => offset : offset;
  // walk the grid in local time; each local tick maps back with the offset in force then
  const toUtc = (local: number): number => {
    const guess = local - off(local - off(x0));
    return local - off(guess);
  };
  const out: number[] = [];
  const first = Math.ceil((x0 + off(x0)) / step - 1e-9) * step;
  for (let local = first, n = 0; n < MAX_TICKS + 2 && out.length < MAX_TICKS; local += step, n += 1) {
    const v = toUtc(local);
    if (v > x1 + step * 1e-9) break;
    // a local time the clock skips maps off the grid, one it repeats maps twice: keep each once
    if (v < x0 - step * 1e-9 || (v + off(v)) % step !== 0 || out.includes(v)) continue;
    out.push(v || 0); // no -0
  }
  return out;
}

const pad = (n: number): string => String(n).padStart(2, "0");

/** Decimals that tell apart ticks `step` seconds apart (sub-second steps only). */
function fracDigits(step: number): number {
  return step > 0 && step < 1 ? Math.min(6, Math.ceil(-Math.log10(step) - 1e-9)) : 0;
}

/**
 * Local wall-clock time of epoch seconds `v`, as precise as ticks `step` seconds apart
 * need: a date for day steps, `HH:MM` for minute steps, `HH:MM:SS` below, and fractions of a
 * second below one second.
 */
export function fmtClock(v: number, step: number): string {
  const digits = fracDigits(step);
  const scale = 10 ** digits;
  const rounded = Math.round(v * scale) / scale;
  const whole = Math.floor(rounded);
  const d = new Date(whole * 1000);
  if (step >= DAY) return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (step >= 60) return hm;
  const hms = `${hm}:${pad(d.getSeconds())}`;
  return digits === 0 ? hms : `${hms}${(rounded - whole).toFixed(digits).slice(1)}`;
}

/** The tooltip's clock: never coarser than seconds. */
export function fmtClockTip(v: number, step: number): string {
  return fmtClock(v, Math.min(step, 1));
}

const UNITS = [
  [3600, "h"],
  [60, "m"],
  [1, "s"],
  [1e-3, "ms"],
] as const;

/**
 * A duration in seconds with its largest whole unit and up to 2 decimals: `0`, `0.5ms`,
 * `30s`, `2m`, `1.5h`.
 *
 * Examples
 * --------
 * >>> fmtSpan(5400)
 * '1.5h'
 */
export function fmtSpan(v: number): string {
  if (!Number.isFinite(v)) return "";
  const a = Math.abs(v);
  if (a === 0) return "0";
  const [unit, name] = UNITS.find(([u]) => a >= u * (1 - 1e-9)) ?? UNITS[UNITS.length - 1];
  const s = `${+(a / unit).toFixed(2)}${name}`;
  return v < 0 ? `−${s}` : s;
}

/** How a LineChart reads its x values. */
export type XAxisKind = "step" | "clock" | "duration";
