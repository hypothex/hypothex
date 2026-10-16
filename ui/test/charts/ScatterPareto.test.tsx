import { afterEach, expect, test } from "bun:test";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { type ScatterPoint, ScatterPareto, paretoFront } from "../../src/charts/ScatterPareto";
import { TooltipHost, hideTip } from "../../src/charts/Tooltip";

afterEach(() => act(() => hideTip()));

const p = (id: string, x: number, y: number): ScatterPoint => ({ id, name: id, color: "var(--c1)", x, y, yLo: y - 0.01, yHi: y + 0.01 });
const pts = [p("A", 1, 0.8), p("B", 2, 0.9), p("C", 3, 0.85), p("D", 4, 0.95)];

test("the front keeps a point only when it beats every cheaper one", () => {
  expect(paretoFront(pts).map((q) => q.id)).toEqual(["A", "B", "D"]);
  expect(paretoFront(pts, false).map((q) => q.id)).toEqual(["A"]);
  expect(paretoFront([p("E", 1, 0.8), p("F", 1, 0.9)]).map((q) => q.id)).toEqual(["F"]);
});

test("x starts at zero on nice ticks; the front is a dashed path; one dot per point", () => {
  const { container } = render(<ScatterPareto points={pts} width={420} xFormat={(v) => `${v}h`} />);
  const svg = container.querySelector("svg.chart") as SVGSVGElement;
  expect(svg.getAttribute("viewBox")).toBe("0 0 420 150");
  const xs = [...svg.querySelectorAll("text.xt")].map((t) => t.textContent);
  expect(xs).toEqual(["0h", "1h", "2h", "3h", "4h"]);
  expect(svg.querySelector("path.front")?.getAttribute("d")?.startsWith("M")).toBe(true);
  expect(svg.querySelectorAll("circle.dot").length).toBe(4);
  expect(svg.querySelectorAll("line.err").length).toBe(4);
});

test("each point carries its id as data-series", () => {
  const { container } = render(<ScatterPareto points={pts} width={420} />);
  expect([...container.querySelectorAll("g.pt")].map((g) => g.getAttribute("data-series"))).toEqual(["A", "B", "C", "D"]);
});

test("tooltip names the run, its score and its cost", () => {
  const { container } = render(
    <>
      <ScatterPareto points={pts} width={420} xName="GPU-h per run" yName="top1" />
      <TooltipHost />
    </>,
  );
  fireEvent.mouseMove(container.querySelector("g.pt") as Element, { clientX: 1, clientY: 1 });
  const tip = screen.getByRole("tooltip");
  expect(tip.querySelector(".h")?.textContent).toBe("A");
  expect([...tip.querySelectorAll(".r span")].map((s) => s.textContent)).toEqual(["top1", "GPU-h per run"]);
});

test("no points: a calm message, no NaN", () => {
  const { container } = render(<ScatterPareto points={[]} width={300} />);
  expect(container.textContent).toContain("no data");
  expect(container.innerHTML).not.toContain("NaN");
});

test("one point at zero cost with no interval: padded domains, no NaN", () => {
  const { container } = render(<ScatterPareto points={[{ id: "z", name: "z", color: "var(--c1)", x: 0, y: 0 }]} width={300} />);
  expect(container.querySelectorAll("circle.dot").length).toBe(1);
  expect(container.innerHTML).not.toContain("NaN");
  expect(container.innerHTML).not.toContain("Infinity");
});
