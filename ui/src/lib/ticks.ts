/**
 * "Nice" axis ticks (spec section 6): steps of 1, 2, 2.5 or 5 × 10^n, ported from the v5
 * mockup's `niceTicks`. Every v5 chart axis goes through these helpers.
 */

const FACTORS = [1, 2, 2.5, 5, 10] as const;

/** Drop float noise (0.30000000000000004 -> 0.3) and negative zero. */
function clean(v: number): number {
  const r = +v.toPrecision(12);
  return r === 0 ? 0 : r;
}

/**
 * The tick step for `span` split in about `count` parts.
 *
 * Examples
 * --------
 * >>> niceStep(1, 4)
 * 0.25
 */
export function niceStep(span: number, count = 4): number {
  if (!Number.isFinite(span) || span <= 0 || !(count >= 1)) return 0;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  for (const f of FACTORS) {
    const step = clean(f * mag);
    if (step >= raw * (1 - 1e-9)) return step;
  }
  return clean(10 * mag);
}

/**
 * Every multiple of the nice step inside `[lo, hi]`, both ends included.
 *
 * Examples
 * --------
 * >>> niceTicks(0, 1, 4)
 * [0, 0.25, 0.5, 0.75, 1]
 */
export function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (!(hi > lo)) return [lo];
  const step = niceStep(hi - lo, count);
  const first = Math.ceil(lo / step - 1e-9);
  const last = Math.floor(hi / step + 1e-9);
  const out: number[] = [];
  for (let k = first; k <= last; k++) out.push(clean(k * step));
  return out;
}

/**
 * `[lo, hi]` rounded out to multiples of the nice step (bar axes start at a tick).
 *
 * Examples
 * --------
 * >>> niceExtent(0, 0.913)
 * [0, 1]
 */
export function niceExtent(lo: number, hi: number, count = 4): [number, number] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (!(hi > lo)) {
    if (lo === 0) return [0, 1];
    const pad = Math.abs(lo) * 0.05;
    return niceExtent(lo - pad, lo + pad, count);
  }
  const step = niceStep(hi - lo, count);
  return [clean(Math.floor(lo / step + 1e-9) * step), clean(Math.ceil(hi / step - 1e-9) * step)];
}

/** Decimals that show `step` exactly: 0.25 -> 2, 0.5 -> 1, 10000 -> 0. */
export function stepDecimals(step: number): number {
  for (let d = 0; d <= 10; d++) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-6 * Math.max(1, Math.abs(scaled))) return d;
  }
  return 10;
}

function compact(v: number): string {
  const a = Math.abs(v);
  const s = a >= 1e6 ? `${+(a / 1e6).toFixed(1)}M` : `${+(a / 1e3).toFixed(1)}k`;
  return v < 0 ? `−${s}` : s;
}

/**
 * A label formatter for `ticks`: the step's decimals, U+2212 minus, and `10k` / `2M` once
 * the largest tick reaches ten thousand.
 *
 * Examples
 * --------
 * >>> [0, 0.25].map(tickFormatter([0, 0.25]))
 * ["0.00", "0.25"]
 */
export function tickFormatter(ticks: readonly number[]): (v: number) => string {
  const step = ticks.length > 1 ? Math.abs((ticks[1] ?? 0) - (ticks[0] ?? 0)) : 0;
  const d = step > 0 ? stepDecimals(step) : 2;
  const big = ticks.some((t) => Math.abs(t) >= 10_000) && d === 0;
  return (v) => {
    if (big && v !== 0) return compact(v);
    const s = Math.abs(v).toFixed(d);
    return v < 0 && Number(s) !== 0 ? `−${s}` : s;
  };
}
