import { expect, test } from "bun:test";
import { render } from "@testing-library/react";
import { ScoreStrip, type StripMark } from "../../src/charts/ScoreStrip";

const marks: StripMark[] = [
  { kind: "other", value: 0.88 },
  { kind: "other", value: 0.87 },
  { kind: "seed", value: 0.905, color: "var(--c1)" },
  { kind: "seed", value: 0.9, color: "var(--c1)" },
  { kind: "this", value: 0.91, color: "var(--c1)" },
];

test("this run large, sibling seeds faint, other configs as ticks, the best interval as a band", () => {
  const { container } = render(<ScoreStrip width={600} marks={marks} band={[0.895, 0.915]} />);
  const svg = container.querySelector("svg.chart") as SVGSVGElement;
  expect(svg.getAttribute("viewBox")).toBe("0 0 600 46");
  expect(svg.querySelectorAll("line.other").length).toBe(2);
  expect(svg.querySelectorAll("circle.sdot.faint").length).toBe(2);
  const dot = svg.querySelector("circle.dot");
  expect([dot?.getAttribute("r"), dot?.getAttribute("fill")]).toEqual(["6", "var(--c1)"]);
  expect(svg.querySelectorAll("rect.sband").length).toBe(1);
  const ticks = [...svg.querySelectorAll("text.xt")].map((t) => Number(t.textContent));
  expect(ticks.length).toBeGreaterThanOrEqual(2);
  expect(ticks.every((v, i) => i === 0 || v > (ticks[i - 1] ?? 0))).toBe(true);
  expect(svg.outerHTML).not.toContain("NaN");
});

test("no marks draws nothing broken", () => {
  const { container } = render(<ScoreStrip width={300} marks={[]} />);
  expect(container.innerHTML).not.toContain("NaN");
});

test("a fixed domain with lo = hi is padded, no NaN", () => {
  const { container } = render(<ScoreStrip width={300} marks={[{ kind: "this", value: 0.5 }]} lo={0.5} hi={0.5} />);
  expect(container.innerHTML).not.toContain("NaN");
  expect(container.querySelectorAll("text.xt").length).toBeGreaterThanOrEqual(2);
});
