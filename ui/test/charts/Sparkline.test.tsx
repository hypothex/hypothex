import { expect, test } from "bun:test";
import { render } from "@testing-library/react";
import { Sparkline, sparkPoints } from "../../src/charts/Sparkline";

test("best-over-time: the best value is at the top; lower-is-better flips", () => {
  expect(sparkPoints([1, 2, 3], 90, 22, false)).toBe("2,19 45,11 88,3");
  expect(sparkPoints([1, 2, 3], 90, 22, true)).toBe("2,3 45,11 88,19");
});

test("equal values and a single value sit in the middle; non-finite values are dropped", () => {
  expect(sparkPoints([5, 5], 90, 22, false)).toBe("2,11 88,11");
  expect(sparkPoints([5], 90, 22, false)).toBe("2,11 88,11");
  expect(sparkPoints([1, Number.NaN, 3], 90, 22, false)).toBe("2,19 88,3");
});

test("renders a labelled 90 × 22 svg, nothing for no values", () => {
  const { container, rerender } = render(<Sparkline values={[0.8, 0.9]} label="best top1 over 7 days" />);
  const svg = container.querySelector("svg.spark");
  expect([svg?.getAttribute("width"), svg?.getAttribute("height"), svg?.getAttribute("aria-label")]).toEqual([
    "90", "22", "best top1 over 7 days",
  ]);
  rerender(<Sparkline values={[]} />);
  expect(container.querySelector("svg")).toBeNull();
});

test("without a label the svg is decorative", () => {
  const { container } = render(<Sparkline values={[1, 2]} />);
  const svg = container.querySelector("svg.spark");
  expect([svg?.getAttribute("role"), svg?.getAttribute("aria-hidden")]).toEqual([null, "true"]);
});
