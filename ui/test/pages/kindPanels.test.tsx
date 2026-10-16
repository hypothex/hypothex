import { describe, expect, test } from "bun:test";
import {
  pickExample,
  readsTraces,
  runViewPanels,
  scopeToRun,
  sentenceCase,
  withoutSweeps,
} from "../../src/pages/components/KindPanels";
import type { PanelSpec } from "../../src/pages/components/types";

const TRACES = [
  { example_id: "T-001", turns: 3, failed: false },
  { example_id: "T-014", turns: 13, failed: true },
];

describe("helpers", () => {
  test("scopeToRun adds the run filter and keeps the rest", () => {
    expect(
      scopeToRun({ type: "curves", title: "Loss", data: { metrics: ["loss"], filter: { status: ["finished"] } } }, "R"),
    ).toEqual({
      type: "curves",
      title: "Loss",
      data: { metrics: ["loss"], filter: { status: ["finished"], run_id: "R" } },
    });
    expect(scopeToRun({ type: "table" }, "R")).toEqual({ type: "table", data: { filter: { run_id: "R" } } });
  });

  test("scopeToRun leaves the cross-config grid unscoped", () => {
    const grid: PanelSpec = { type: "grid", title: "same item across configs" };
    expect(scopeToRun(grid, "R")).toEqual({ type: "grid", title: "same item across configs" });
    expect(scopeToRun(grid, "R")).toBe(grid);
  });

  test("pickExample prefers a failed trace", () => {
    expect(pickExample(TRACES)).toBe("T-014");
    expect(pickExample([{ example_id: "a", turns: 1, failed: false }])).toBe("a");
    expect(pickExample([])).toBeNull();
  });
});

test("runViewPanels: sentence-case titles; no trace panels for a run without traces", () => {
  const agent: PanelSpec[] = [
    { type: "trace", title: "steps" },
    { type: "grid", title: "same item across configs" },
    { type: "table", title: "tokens per turn", data: { source: "traces" } },
  ];
  expect(sentenceCase("tokens per turn")).toBe("Tokens per turn");
  expect(sentenceCase("")).toBe("");
  expect(agent.map(readsTraces)).toEqual([true, false, true]);
  expect(runViewPanels(agent, 0).map((p) => p.title)).toEqual(["Same item across configs"]);
  expect(runViewPanels(agent, 2).map((p) => p.title)).toEqual([
    "Steps",
    "Same item across configs",
    "Tokens per turn",
  ]);
  // traces not loaded yet: keep every panel
  expect(runViewPanels(agent)).toHaveLength(3);
});

describe("sweep metrics stay out of the run's over-time curves (UI-F10b)", () => {
  const point = (name: string, step: number) => ({ run_id: "R", group_id: "g", seed: 1, name, step, value: 1 });
  const rows = [point("cpu_pct", 0), point("cpu_pct", 33), point("sweep/rps", 1), point("sweep/rps", 128)];
  const overTime: PanelSpec = { type: "curves", title: "over time" };

  test("withoutSweeps drops sweep/* rows of a curves panel without a metric list", () => {
    const result = { type: "curves" as const, title: "over time", rows, meta: { metrics: ["cpu_pct", "sweep/rps"] } };
    const out = withoutSweeps(result, overTime);
    expect(out.rows.map((r) => r.name)).toEqual(["cpu_pct", "cpu_pct"]);
    expect(out.meta.metrics).toEqual(["cpu_pct"]);
    // a panel that names the sweep metric keeps it; other panel types are left alone
    const listed: PanelSpec = { type: "curves", data: { metrics: ["sweep/rps"] } };
    expect(withoutSweeps(result, listed)).toBe(result);
    const table = { type: "table" as const, title: "t", rows, meta: {} };
    expect(withoutSweeps(table, { type: "table" })).toBe(table);
  });
});

describe("bounded visible run curve requests (PERF-F9c)", () => {
  test("implicit curves request only displayed history names with a per-series cap", () => {
    const prepared = runViewPanels(
      [{ type: "curves", title: "over time", data: { step_metric: "elapsed" } }],
      undefined,
      ["loss", "sweep/rps", "elapsed", "gpu_pct"],
    );
    expect(prepared[0]?.data).toEqual({
      step_metric: "elapsed", metrics: ["loss", "gpu_pct"], max_points: 500,
    });
    expect(runViewPanels([{ type: "curves" }], undefined, ["step", "sweep/rps"])[0]?.data).toEqual({
      metrics: [], max_points: 500,
    });
  });

  test("explicit metric choices, including sweep and step names, stay intact", () => {
    const source: PanelSpec = { type: "curves", data: { metrics: ["sweep/rps", "step"], max_points: 120 } };
    expect(runViewPanels([source], undefined, ["loss"])[0]?.data).toEqual(source.data);
    expect(source.data?.metrics).toEqual(["sweep/rps", "step"]);
    expect(runViewPanels([{ type: "curves", data: { metrics: [] } }], undefined, ["loss"])[0]?.data).toEqual({
      metrics: [], max_points: 500,
    });
  });

  test("more than 100 displayed names split without truncation", () => {
    const names = Array.from({ length: 205 }, (_, i) => `metric_${i}`);
    const specs = runViewPanels([{ type: "curves", title: "metrics" }], undefined, names);
    expect(specs.map((p) => p.data?.metrics?.length)).toEqual([100, 100, 5]);
    expect(specs.flatMap((p) => p.data?.metrics ?? [])).toEqual(names);
    expect(specs.map((p) => p.title)).toEqual(["Metrics · 1–100", "Metrics · 101–200", "Metrics · 201–205"]);
  });
});
