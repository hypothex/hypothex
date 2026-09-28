import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import {
  MINUS,
  f2,
  f3,
  f4,
  fmtP,
  fmtValue,
  kStep,
  linear,
  logScale,
  niceDomain,
  signed,
  tickDecimals,
  tickFormat,
  useElementWidth,
} from "../../src/charts/Scale";

afterEach(cleanup);

describe("number formats", () => {
  test("fixed decimals use a real minus and never print -0", () => {
    expect(f2(0.1534)).toBe("0.15");
    expect(f3(0.87412)).toBe("0.874");
    expect(f4(0.92216)).toBe("0.9222");
    expect(f3(-0.0374)).toBe(`${MINUS}0.037`);
    expect(f3(-0.0001)).toBe("0.000");
  });
  test("signed adds a plus for gains", () => {
    expect(signed(0.0371)).toBe("+0.037");
    expect(signed(-0.0561)).toBe(`${MINUS}0.056`);
    expect(signed(0)).toBe("0.000");
    expect(signed(0.26312, 3)).toBe("+0.263");
  });
  test("p-values: two decimals, three below 0.01, or < 0.001", () => {
    expect(fmtP(0.1459)).toBe("0.15");
    expect(fmtP(0.0289)).toBe("0.03");
    expect(fmtP(0.0042)).toBe("0.004");
    expect(fmtP(0.0004)).toBe("< 0.001");
  });
  test("free numbers: separators for integers, 3 significant digits for small", () => {
    expect(fmtValue(40000)).toBe("40,000");
    expect(fmtValue(250)).toBe("250");
    expect(fmtValue(1234.56)).toBe("1,235");
    expect(fmtValue(0.037)).toBe("0.037");
    expect(fmtValue(0.0064)).toBe("0.0064");
    expect(fmtValue(0.92216)).toBe("0.922");
    expect(fmtValue(-0.0561)).toBe(`${MINUS}0.0561`);
    expect(fmtValue(Number.NaN)).toBe("NaN");
  });
  test("steps compact to k and M", () => {
    expect(kStep(0)).toBe("0");
    expect(kStep(999)).toBe("999");
    expect(kStep(1500)).toBe("1.5k");
    expect(kStep(20000)).toBe("20k");
    expect(kStep(1_200_000)).toBe("1.2M");
  });
});

describe("scales", () => {
  test("tickDecimals follows the tick step", () => {
    expect(tickDecimals([0.78, 0.8, 0.82])).toBe(2);
    expect(tickDecimals([0.875, 0.88, 0.885])).toBe(3);
    expect(tickDecimals([0, 5000, 10000])).toBe(0);
    expect(tickDecimals([1])).toBe(2);
  });
  test("tickFormat labels ticks with the tick step's decimals", () => {
    const fmt = tickFormat([0.875, 0.88, 0.885]);
    expect(fmt(0.88)).toBe("0.880");
    expect(tickFormat([0, 5000])(5000)).toBe("5000");
    expect(tickFormat([-0.02, 0])(-0.02)).toBe(`${MINUS}0.02`);
  });
  test("niceDomain covers the data and survives degenerate input", () => {
    expect(niceDomain([0.8278, 0.953])).toEqual([0.82, 0.96]);
    expect(niceDomain([])).toEqual([0, 1]);
    const [lo, hi] = niceDomain([0.5, 0.5]);
    expect(lo).toBeLessThan(0.5);
    expect(hi).toBeGreaterThan(0.5);
    expect(niceDomain([Number.NaN, 2, 4])).toEqual([2, 4]);
  });
  test("linear maps the domain onto the range and inverts", () => {
    const s = linear([0, 10], 100, 200);
    expect(s.at(0)).toBe(100);
    expect(s.at(5)).toBe(150);
    expect(s.invert(175)).toBe(7.5);
    expect(s.ticks[0]).toBe(0);
    expect(s.ticks.at(-1)).toBe(10);
  });
  test("logScale puts decades evenly and ticks at 1-2-4", () => {
    const s = logScale([0.1, 10], 0, 200);
    expect(s.at(0.1)).toBeCloseTo(0, 6);
    expect(s.at(1)).toBeCloseTo(100, 6);
    expect(s.at(10)).toBeCloseTo(200, 6);
    expect(s.ticks).toEqual([0.1, 0.2, 0.4, 1, 2, 4, 10]);
    expect(Number.isFinite(s.at(0))).toBe(true);
  });
});

function Probe({ fallback }: { fallback: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(fallback);
  return <div ref={ref}>w={width}</div>;
}

describe("useElementWidth", () => {
  test("uses the fallback when layout reports 0", () => {
    render(<Probe fallback={640} />);
    expect(screen.getByText("w=640")).toBeTruthy();
  });
  test("uses the measured width when layout reports one", () => {
    const orig = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function () {
      return { width: 512.4, height: 10, top: 0, left: 0, right: 512.4, bottom: 10, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    };
    try {
      render(<Probe fallback={640} />);
      expect(screen.getByText("w=512")).toBeTruthy();
    } finally {
      HTMLElement.prototype.getBoundingClientRect = orig;
    }
  });
});
