import { describe, expect, test } from "bun:test";
import { niceExtent, niceStep, niceTicks, stepDecimals, tickFormatter } from "../../src/lib/ticks";

/** 0.25 -> 2.5, 2000 -> 2, 0.05 -> 5 */
const mantissa = (step: number): number => +(step / 10 ** Math.floor(Math.log10(step) + 1e-9)).toPrecision(6);

describe("niceStep", () => {
  test("rounds span / count up to 1, 2, 2.5 or 5 × 10^n", () => {
    expect([niceStep(1, 4), niceStep(10, 4), niceStep(30000, 4), niceStep(0.0316, 6), niceStep(7, 4)]).toEqual([
      0.25, 2.5, 10000, 0.01, 2,
    ]);
  });

  test("is 0 for an empty or invalid span", () => {
    expect([niceStep(0), niceStep(-1), niceStep(Number.NaN), niceStep(Number.POSITIVE_INFINITY)]).toEqual([0, 0, 0, 0]);
  });
});

describe("niceTicks", () => {
  test("returns the step multiples inside [lo, hi], ends included", () => {
    expect(niceTicks(0, 1, 4)).toEqual([0, 0.25, 0.5, 0.75, 1]);
    expect(niceTicks(0.8815, 0.9131, 6)).toEqual([0.89, 0.9, 0.91]);
    expect(niceTicks(0, 30000, 4)).toEqual([0, 10000, 20000, 30000]);
    expect(niceTicks(0.1, 0.7, 4)).toEqual([0.2, 0.4, 0.6]);
  });

  test("crosses zero without a negative zero", () => {
    const ticks = niceTicks(-1, 1, 4);
    expect(ticks).toEqual([-1, -0.5, 0, 0.5, 1]);
    expect(Object.is(ticks[2], 0)).toBe(true);
  });

  test("degenerate ranges", () => {
    expect(niceTicks(5, 5)).toEqual([5]);
    expect(niceTicks(2, 1)).toEqual([2]);
    expect(niceTicks(Number.NaN, 1)).toEqual([]);
  });

  test("any range gives >= 2 ascending ticks on one 1/2/2.5/5 step", () => {
    let s = 7;
    const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 300; i++) {
      const scale = 10 ** Math.floor(rnd() * 12 - 6);
      const lo = (rnd() - 0.5) * scale * 10;
      const hi = lo + (0.01 + rnd()) * scale;
      const ticks = niceTicks(lo, hi, 4);
      expect(ticks.length).toBeGreaterThanOrEqual(2);
      expect(ticks[0]).toBeGreaterThanOrEqual(lo - Math.abs(lo) * 1e-9 - 1e-15);
      expect(ticks.at(-1)).toBeLessThanOrEqual(hi + Math.abs(hi) * 1e-9 + 1e-15);
      const step = (ticks[1] ?? 0) - (ticks[0] ?? 0);
      expect([1, 2, 2.5, 5]).toContain(mantissa(step));
    }
  });
});

describe("niceExtent", () => {
  test("rounds a domain out to step multiples; zero stays zero", () => {
    expect(niceExtent(0, 0.913, 4)).toEqual([0, 1]);
    expect(niceExtent(3, 97, 4)).toEqual([0, 100]);
    expect(niceExtent(-0.3, 0.8, 4)).toEqual([-0.5, 1]);
  });

  test("pads an empty domain instead of dividing by zero", () => {
    expect(niceExtent(0, 0)).toEqual([0, 1]);
    expect(niceExtent(5, 5)).toEqual([4.6, 5.4]);
    expect(niceExtent(Number.NaN, 1)).toEqual([0, 1]);
  });
});

describe("tickFormatter", () => {
  test("shows just enough decimals for the step (2.5 steps need two)", () => {
    expect(stepDecimals(0.25)).toBe(2);
    expect(stepDecimals(0.5)).toBe(1);
    expect(stepDecimals(10000)).toBe(0);
    expect(niceTicks(0, 1, 4).map(tickFormatter(niceTicks(0, 1, 4)))).toEqual(["0.00", "0.25", "0.50", "0.75", "1.00"]);
    expect([0.89, 0.9, 0.91].map(tickFormatter([0.89, 0.9, 0.91]))).toEqual(["0.89", "0.90", "0.91"]);
  });

  test("uses a typographic minus and compacts ten thousand and up", () => {
    expect([-0.5, 0, 0.5].map(tickFormatter([-0.5, 0, 0.5]))).toEqual(["−0.5", "0.0", "0.5"]);
    expect([0, 10000, 20000].map(tickFormatter([0, 10000, 20000]))).toEqual(["0", "10k", "20k"]);
    expect([0, 2_000_000].map(tickFormatter([0, 2_000_000]))).toEqual(["0", "2M"]);
  });
});
