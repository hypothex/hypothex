/**
 * Scales, number formats, and width measurement shared by every chart.
 *
 * All chart math goes through these helpers so that the leaderboard, curves, and
 * later panels format numbers the same way (U+2212 minus, tabular decimals).
 */
import { scaleLinear, scaleLog } from "d3-scale";
import { format } from "d3-format";
import { useLayoutEffect, useRef, useState, type RefObject } from "react";

/** A numeric position function, value to pixel. */
export type Pos = (v: number) => number;

/** Typographic minus sign used for every negative number on screen. */
export const MINUS = "−";

function fixed(v: number, digits: number): string {
  const s = Math.abs(v).toFixed(digits);
  return v < 0 && Number(s) !== 0 ? MINUS + s : s;
}

/** Format with 2 decimals, e.g. `0.15`. */
export const f2 = (v: number): string => fixed(v, 2);
/** Format with 3 decimals, e.g. `0.874`. */
export const f3 = (v: number): string => fixed(v, 3);
/** Format with 4 decimals, e.g. `0.9222`. */
export const f4 = (v: number): string => fixed(v, 4);

/** Format a difference with an explicit sign, e.g. `+0.037` or `−0.037`. */
export function signed(v: number, digits = 3): string {
  const s = fixed(v, digits);
  return v > 0 && Number(s) !== 0 ? `+${s}` : s;
}

/**
 * Format a p-value: two decimals, three below 0.01 (never `0.00`), `< 0.001` when tiny.
 *
 * Same rule as the server's `hypothex.core.headlines.fmt_p`, so headlines and panels agree.
 */
export function fmtP(p: number): string {
  if (p < 0.001) return "< 0.001";
  return p < 0.01 ? p.toFixed(3) : p.toFixed(2);
}

const sig3 = format(".3~r");
const grouped = format(",");
const rounded = format(",.0f");

/**
 * Format a free-standing number for a stat strip or tooltip.
 *
 * Integers get thousands separators, large numbers are rounded, and small numbers
 * keep three significant digits.
 */
export function fmtValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return grouped(v).replace("-", MINUS);
  if (Math.abs(v) >= 100) return rounded(v).replace("-", MINUS);
  return sig3(v).replace("-", MINUS);
}

/** Format a training step compactly: `0`, `999`, `1.5k`, `20k`, `1.2M`. */
export function kStep(s: number): string {
  if (Math.abs(s) >= 1e6) return `${+(s / 1e6).toFixed(1)}M`;
  if (Math.abs(s) >= 1e3) return `${+(s / 1e3).toFixed(1)}k`;
  return String(s);
}

/** Number of decimals needed to tell adjacent ticks apart. */
export function tickDecimals(ticks: number[]): number {
  if (ticks.length < 2) return 2;
  const step = Math.abs((ticks[1] ?? 0) - (ticks[0] ?? 0));
  if (step === 0) return 2;
  return Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
}

/** A tick label formatter with just enough decimals for `ticks`, e.g. `0.78`, `0.885`. */
export function tickFormat(ticks: number[]): (v: number) => string {
  const d = tickDecimals(ticks);
  return (v) => fixed(v, d);
}

/**
 * Return a padded, nice domain covering all finite values.
 *
 * Empty input gives `[0, 1]`; a single distinct value is widened by 1% of its
 * magnitude (or 0.01 at zero) so the scale never divides by zero.
 */
export function niceDomain(values: number[]): [number, number] {
  const xs = values.filter(Number.isFinite);
  if (xs.length === 0) return [0, 1];
  let lo = Math.min(...xs);
  let hi = Math.max(...xs);
  if (lo === hi) {
    const pad = lo === 0 ? 0.01 : Math.abs(lo) * 0.01;
    lo -= pad;
    hi += pad;
  }
  const d = scaleLinear().domain([lo, hi]).nice(8).domain();
  return [d[0] ?? lo, d[1] ?? hi];
}

/** A linear scale with its ticks. */
export interface LinearScale {
  at: Pos;
  ticks: number[];
  domain: [number, number];
  invert: Pos;
}

/** Build a linear scale over `domain` mapped to `[r0, r1]`, with about `count` ticks. */
export function linear(domain: [number, number], r0: number, r1: number, count = 8): LinearScale {
  const s = scaleLinear().domain(domain).range([r0, r1]);
  return { at: (v) => s(v), ticks: s.ticks(count), domain, invert: (px) => s.invert(px) };
}

/**
 * Build a log scale over positive values mapped to `[r0, r1]`.
 *
 * Ticks are the 1-2-4 steps of each decade inside the domain, as in the mockups.
 */
export function logScale(domain: [number, number], r0: number, r1: number): LinearScale {
  const lo = Math.max(domain[0], 1e-12);
  const hi = Math.max(domain[1], lo * 1.0001);
  const s = scaleLog().domain([lo, hi]).range([r0, r1]).clamp(false);
  const ticks: number[] = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    for (const m of [1, 2, 4]) {
      const t = +(m * 10 ** e).toPrecision(6);
      if (t >= lo && t <= hi) ticks.push(t);
    }
  }
  return {
    at: (v) => s(Math.max(v, 1e-12)),
    ticks,
    domain: [lo, hi],
    invert: (px) => s.invert(px),
  };
}

/**
 * Measure an element's width, falling back to `fallback` when layout is unknown.
 *
 * Charts render at `fallback` first (and in test DOMs, where width is 0), then
 * re-render at the measured width and on every resize.
 */
export function useElementWidth<T extends HTMLElement>(
  fallback: number,
): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = (): void => {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setWidth(Math.round(w));
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}
