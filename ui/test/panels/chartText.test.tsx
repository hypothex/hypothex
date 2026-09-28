/**
 * Chart text must not scale with the chart: every SVG chart is drawn at its measured width
 * in CSS px (no viewBox), and its text uses the fixed sizes in `FS`.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { FS } from "../../src/charts/Scale";
import { DIST_FALLBACK_W, DistributionPanel } from "../../src/panels/Distribution";
import { GRID_FALLBACK_W, GridPanel, labelGutter } from "../../src/panels/Grid";
import type { PanelResult } from "../../src/panels/index";
import { SCATTER_FALLBACK_W, ScatterPanel, scatterHeight } from "../../src/panels/Scatter";
import { SignTestChart } from "../../src/pages/components/ExampleCharts";

afterEach(cleanup);

const result = (type: PanelResult["type"], rows: unknown[], meta: Record<string, unknown> = {}): PanelResult => ({
  type,
  title: type,
  rows: rows as Record<string, unknown>[],
  meta,
});

const scatter = result(
  "scatter",
  [
    { group_id: "v1", label: "v1", x: "v1", x_lo: null, x_hi: null, y: 0.4, y_lo: 0.35, y_hi: 0.45, seeds: [], pareto: false, regression: false },
    { group_id: "v2", label: "v2", x: "v2", x_lo: null, x_hi: null, y: 0.5, y_lo: 0.45, y_hi: 0.55, seeds: [], pareto: false, regression: false },
  ],
  { x_type: "ordinal", x_label: "version", y_label: "solved" },
);
const grid = result("grid", [
  { item_id: "t1", group_id: "gA", value: 1 },
  { item_id: "t2", group_id: "gA", value: 0 },
]);
const dist = result("distribution", [
  { group_id: "g1", label: "base", n: 2, p50: 20, p95: 80, p99: 200, ecdf: [[10, 0.5], [200, 1]], seeds: [] },
]);

const charts: [string, () => ReactElement, number][] = [
  ["scatter", () => <ScatterPanel result={scatter} />, SCATTER_FALLBACK_W],
  ["grid", () => <GridPanel result={grid} />, GRID_FALLBACK_W],
  ["distribution", () => <DistributionPanel result={dist} />, DIST_FALLBACK_W],
];

describe.each(charts)("%s", (_name, draw, fallback) => {
  test("draws at a px width with no viewBox scaling", () => {
    const { container } = render(draw());
    const svg = container.querySelector("svg[role='img']");
    expect(svg?.getAttribute("viewBox")).toBeNull();
    expect(svg?.getAttribute("width")).toBe(String(fallback));
  });

  test("every text uses a fixed px size from FS", () => {
    const { container } = render(draw());
    const sizes = new Set(
      [...container.querySelectorAll("svg[role='img'] text")].map((t) => (t as SVGElement).style.fontSize),
    );
    for (const s of sizes) expect([`${FS.tick}px`, `${FS.label}px`]).toContain(s);
  });
});

test("scatter height follows the width within 240..360 px", () => {
  expect(scatterHeight(640)).toBe(360);
  expect(scatterHeight(460)).toBe(259);
  expect(scatterHeight(200)).toBe(240);
});

test("grid label gutter grows with the longest label", () => {
  expect(labelGutter([{ group_id: "a", label: "v1" }])).toBe(150);
  expect(labelGutter([{ group_id: "a", label: "Sonnet 5 + scorer with tools" }])).toBe(252);
});

test("sign test chart draws at a px width", () => {
  const { container } = render(<SignTestChart fixed={9} broken={3} />);
  const svg = container.querySelector("svg");
  expect(svg?.getAttribute("viewBox")).toBeNull();
  expect(svg?.getAttribute("width")).toBe("640");
});
