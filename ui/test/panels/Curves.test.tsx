import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import {
  Curves,
  buildCurves,
  cellKey,
  isLoss,
  isLr,
  meanSeries,
  valueAt,
  type CheckpointJson,
  type CurvePoint,
} from "../../src/panels/Curves";

afterEach(cleanup);

/*
 * Two groups x two seeds, steps 0..1000 every 100 (mirrors docs/mockups/kinds/training):
 *   train_loss = 0.8 exp(-step / 400) + 0.1 + 0.01 seed
 *   val_top1   = 0.9 - 0.4 exp(-step / 300) + 0.002 seed
 *   lr         = 3e-4 (1 - 0.9 step / 1000)
 * base seed 2 spikes at step 500 (train_loss 3.0, val_top1 0.44);
 * aug seed 2 is killed at step 600 (no points after it).
 */
const loss = (s: number, seed: number) => 0.8 * Math.exp(-s / 400) + 0.1 + 0.01 * seed;
const top1 = (s: number, seed: number) => 0.9 - 0.4 * Math.exp(-s / 300) + 0.002 * seed;
const lr = (s: number) => 3e-4 * (1 - (0.9 * s) / 1000);
const RUNS = [
  { run_id: "b1", group_id: "base", seed: 1, last: 1000 },
  { run_id: "b2", group_id: "base", seed: 2, last: 1000 },
  { run_id: "a1", group_id: "aug", seed: 1, last: 1000 },
  { run_id: "a2", group_id: "aug", seed: 2, last: 600 },
];
function points(): CurvePoint[] {
  const out: CurvePoint[] = [];
  for (const r of RUNS) {
    for (let s = 0; s <= r.last; s += 100) {
      const base = { run_id: r.run_id, group_id: r.group_id, seed: r.seed, step: s };
      out.push({ ...base, name: "lr", value: lr(s) });
      out.push({ ...base, name: "train_loss", value: r.run_id === "b2" && s === 500 ? 3.0 : loss(s, r.seed) });
      out.push({ ...base, name: "val_top1", value: r.run_id === "b2" && s === 500 ? 0.44 : top1(s, r.seed) });
    }
  }
  return out;
}
const CKPTS: CheckpointJson[] = [
  { run_id: "b1", step: 900, value: top1(900, 1), best: true },
  { run_id: "b2", step: 400, value: top1(400, 2), best: true },
  { run_id: "a1", step: 1000, value: top1(1000, 1), best: true },
  { run_id: "a2", step: 600, value: top1(600, 2), best: true },
  { run_id: "a1", step: 500, value: top1(500, 1), best: false },
];
const META = {
  groups: [
    { group_id: "base", label: "base" },
    { group_id: "aug", label: "+aug" },
  ],
  checkpoints: CKPTS,
  events: [
    { run_id: "b2", step: 500, kind: "spike" },
    { run_id: "a2", step: 600, kind: "killed" },
  ],
};
const result = (rows = points(), meta: Record<string, unknown> = META): PanelResult => ({
  type: "curves",
  title: "Curves",
  rows: rows as unknown as Array<Record<string, unknown>>,
  meta,
});

describe("model", () => {
  test("name helpers", () => {
    expect(isLr("lr")).toBe(true);
    expect(isLr("train/lr")).toBe(true);
    expect(isLr("learning_rate")).toBe(true);
    expect(isLr("clr_score")).toBe(false);
    expect(isLoss("val_loss")).toBe(true);
    expect(isLoss("val_top1")).toBe(false);
  });

  test("meanSeries averages runs per step; valueAt holds the last value", () => {
    const m = meanSeries([
      { run_id: "x", seed: 1, points: [[0, 1], [10, 3]] },
      { run_id: "y", seed: 2, points: [[0, 3]] },
    ]);
    expect(m).toEqual([[0, 2], [10, 3]]);
    expect(valueAt(m, 5)).toBe(2);
    expect(valueAt(m, -1)).toBeNull();
  });

  test("groups keep meta order, lr rows go last, cells hold seeds and mean", () => {
    const m = buildCurves(points(), META);
    expect(m.groups.map((g) => g.label)).toEqual(["base", "+aug"]);
    expect(m.names).toEqual(["train_loss", "val_top1", "lr"]);
    expect(m.maxStep).toBe(1000);
    const cell = m.cells.get(cellKey("base", "val_top1"));
    expect(cell?.runs.map((r) => r.run_id)).toEqual(["b1", "b2"]);
    // mean at step 100 = (0.615387 + 0.617387) / 2, with 0.9 - 0.4 exp(-1/3) = 0.613387.
    expect(valueAt(cell?.mean ?? [], 100)).toBeCloseTo(0.616387, 5);
    expect(m.cells.get(cellKey("aug", "train_loss"))?.runs[1]?.points.length).toBe(7);
  });

  test("scales: log for losses, lr from zero, spike window left out", () => {
    const m = buildCurves(points(), META);
    expect(m.scales.train_loss?.kind).toBe("log");
    // Max outside the spike window is step 0, seed 2: 0.8 + 0.1 + 0.02 = 0.92; x 1.1 = 1.012.
    expect(m.scales.train_loss?.domain[1]).toBeCloseTo(1.012, 6);
    expect(m.scales.val_top1?.kind).toBe("linear");
    // Min outside the window is step 0, seed 1: 0.502; span 0.502..0.9007 (a1 at 1000), pad 5%.
    expect(m.scales.val_top1?.domain[0]).toBeGreaterThan(0.44);
    expect(m.scales.lr).toEqual({ kind: "lr", domain: [0, 3e-4] });
  });

  test("best checkpoints land on the matching metric row; events get their group", () => {
    const m = buildCurves(points(), META);
    expect(m.checkpoints.map((c) => [c.run_id, c.name, c.group_id])).toEqual([
      ["b1", "val_top1", "base"],
      ["b2", "val_top1", "base"],
      ["a1", "val_top1", "aug"],
      ["a2", "val_top1", "aug"],
    ]);
    const odd = buildCurves(points(), { ...META, checkpoints: [{ run_id: "b1", step: 950, value: 0.5, best: true }] });
    expect(odd.checkpoints[0]?.name).toBe("val_top1");
    expect(m.events.map((e) => [e.kind, e.group_id])).toEqual([
      ["spike", "base"],
      ["killed", "aug"],
    ]);
  });

  test("groups missing from meta are appended; bad points are skipped", () => {
    const rows = [
      ...points().filter((p) => p.group_id === "base"),
      { run_id: "z1", group_id: "zeta", seed: 1, name: "train_loss", step: 0, value: Number.NaN },
      { run_id: "z1", group_id: "zeta", seed: 1, name: "train_loss", step: 100, value: 0.5 },
    ];
    const m = buildCurves(rows, { groups: [{ group_id: "base", label: "base" }] });
    expect(m.groups.map((g) => g.group_id)).toEqual(["base", "zeta"]);
    expect(m.cells.get(cellKey("zeta", "train_loss"))?.runs[0]?.points).toEqual([[100, 0.5]]);
  });
});

describe("Curves panel", () => {
  test("one column per group; faint seeds, bold mean, lr area", () => {
    const { container } = render(<Curves result={result()} />);
    const cols = [...container.querySelectorAll(".curve-col")];
    expect(cols.map((c) => c.querySelector("text.ttl")?.textContent)).toEqual(["base", "+aug"]);
    expect(container.querySelectorAll(".curves svg.hx-chart[role=img]").length).toBe(1);
    // 4 runs x 2 non-lr metrics; 2 groups x 2 means; one lr area per group.
    expect(container.querySelectorAll("svg[role=img] path.sl").length).toBe(8);
    expect(container.querySelectorAll("svg[role=img] path.ml").length).toBe(4);
    expect(container.querySelectorAll("path.lra").length).toBe(2);
    expect([...container.querySelectorAll("svg[role=img] text.lbl")].map((t) => t.textContent)).toEqual([
      "train_loss",
      "val_top1",
      "lr",
    ]);
    expect(container.querySelector(".curve-cell[data-name=lr] text.lbl-s")?.textContent).toBe("peak 0.0003");
  });

  test("spike, kill, clip carets and best checkpoints are marked", () => {
    const { container } = render(<Curves result={result()} />);
    const chart = container.querySelector("svg[role=img]") as SVGElement;
    const base = chart.querySelector('.curve-col[data-group="base"]') as Element;
    const aug = chart.querySelector('.curve-col[data-group="aug"]') as Element;
    expect(base.querySelectorAll("line.ev").length).toBe(3);
    expect(base.querySelectorAll("path.evg").length).toBe(1);
    expect(base.querySelector(".event.spike text.lbl-s")?.textContent).toBe("500");
    const carets = [...base.querySelectorAll(".clip-caret text")].map((t) => t.textContent);
    expect(carets).toEqual(["3", "0.44"]);
    expect(aug.querySelectorAll("path.m-fail").length).toBe(2);
    expect(aug.querySelectorAll("line.ev").length).toBe(0);
    expect(chart.querySelectorAll("circle.m-best").length).toBe(4);
    expect([...container.querySelectorAll(".key span")].map((s) => s.textContent)).toEqual([
      "seed",
      "mean",
      "best ckpt",
      "spike",
      "killed",
    ]);
  });

  test("hover shows every seed and the mean at the nearest step", () => {
    const { container } = render(<Curves result={result()} />);
    // Fallback width 960: colW = (960 - 104 - 36) / 2 = 410; step 300 sits at 104 + 0.3 * 410 = 227.
    const hit = container.querySelector('rect.hit[data-hit="base"]') as Element;
    fireEvent.mouseMove(hit, { clientX: 229, clientY: 50 });
    const lines = screen.getByRole("tooltip").textContent?.split("\n") ?? [];
    // train_loss at 300: 0.8 exp(-0.75) + 0.11 = 0.487893, + 0.01 = 0.497893, mean 0.492893.
    expect(lines[0]).toBe("base, step 300");
    expect(lines[1]).toBe("train_loss  s1 0.488  s2 0.498  mean 0.493");
    expect(container.querySelector("line.xh")).not.toBeNull();
    fireEvent.mouseLeave(hit);
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(container.querySelector("line.xh")).toBeNull();
  });

  test("more than three groups wrap into a second band; empty rows show a note", () => {
    const rows = [1, 2, 3, 4].map((i) => ({
      run_id: `r${i}`,
      group_id: `g${i}`,
      seed: 1,
      name: "loss",
      step: 0,
      value: 1,
    }));
    const { container } = render(<Curves result={result(rows, {})} />);
    expect(container.querySelectorAll("svg[role=img]").length).toBe(2);
    cleanup();
    render(<Curves result={result([], {})} />);
    expect(screen.getByText("No metric history yet")).toBeTruthy();
  });
});

describe("small multiple titles", () => {
  const perRun = (groups: Record<string, unknown>[]): PanelResult => ({
    type: "curves",
    title: "Utilisation",
    rows: RUNS.map((r) => ({ run_id: r.run_id, group_id: r.run_id, seed: r.seed, name: "gpu", step: 0, value: 1 })),
    meta: { groups },
  });

  test("run labels from meta.groups title each column", () => {
    const groups = RUNS.map((r) => ({ group_id: r.run_id, label: r.group_id, run_label: `${r.group_id} r${r.seed}` }));
    const { container } = render(<Curves result={perRun(groups)} />);
    const titles = [...container.querySelectorAll("text.ttl")].map((t) => t.textContent);
    expect(titles).toEqual(["base r1", "base r2", "aug r1", "aug r2"]);
  });

  test("repeated labels without run labels get the run's seed", () => {
    const groups = RUNS.map((r) => ({ group_id: r.run_id, label: r.group_id }));
    const model = buildCurves(perRun(groups).rows as unknown as CurvePoint[], { groups });
    expect(model.groups.map((g) => g.label)).toEqual(["base s1", "base s2", "aug s1", "aug s2"]);
  });

  test("unique labels are left alone", () => {
    const model = buildCurves(points(), { groups: [{ group_id: "base", label: "base" }, { group_id: "aug", label: "+aug" }] });
    expect(model.groups.map((g) => g.label)).toEqual(["base", "+aug"]);
  });
});
