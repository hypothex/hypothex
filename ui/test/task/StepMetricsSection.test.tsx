import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { cleanup } from "@testing-library/react";
import { StepMetricsSection, type StepMetricsSectionProps } from "../../src/task/StepMetricsSection";
import type { CurvePoint, XMode } from "../../src/task/stepMetrics";
import { listIdentities, parseSelection } from "../../src/task/useRunSelection";
import { renderWithClient } from "../pages/helpers";
import { makeTaskRuns } from "./fixtures";

const original = HTMLElement.prototype.getBoundingClientRect;
beforeEach(() => {
  HTMLElement.prototype.getBoundingClientRect = () => ({ width: 420, left: 0 }) as DOMRect;
});
afterEach(() => {
  HTMLElement.prototype.getBoundingClientRect = original;
  cleanup();
});

// epoch seconds (a wall clock around 2026-10-15), one point a minute for 30 min
const T0 = 1_792_152_689;
const POINTS: CurvePoint[] = Array.from({ length: 31 }, (_, i) => ({
  run_id: "run-a1", group_id: "g-a", seed: 1, name: "train/loss", step: i * 100, value: 2 - i / 30, t: T0 + i * 60,
}));

function draw(x: XMode): string[] {
  const items = listIdentities(parseSelection(new URLSearchParams(), { sortDir: "desc" }), makeTaskRuns());
  const props: StepMetricsSectionProps = {
    curves: { points: POINTS, error: null, loading: false },
    sections: [{ title: "train", metrics: ["train/loss"] }],
    items,
    colorOf: () => "var(--c1)",
    highlight: null,
    query: "",
    smoothing: 0,
    x,
    seeds: "mean",
    storageKey: "toy-proj/toy-task",
  };
  const { container } = renderWithClient(<StepMetricsSection {...props} />);
  return [...container.querySelectorAll("svg.chart text.xt")].map((t) => t.textContent ?? "");
}

describe("StepMetricsSection x axis", () => {
  test("step: step ticks from 0", () => {
    expect(draw("step")[0]).toBe("0");
  });

  test("wall time: clock ticks over the data, not epoch numbers from 0", () => {
    const ticks = draw("wall");
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    for (const t of ticks) expect(t).toMatch(/^\d\d:\d\d$/);
  });

  test("relative time: durations with units", () => {
    expect(draw("relative")).toEqual(["0", "10m", "20m", "30m"]);
  });
});
