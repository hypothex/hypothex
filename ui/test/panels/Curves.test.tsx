import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import {
  Curves,
  buildCurves,
  cellKey,
  isLoss,
  LABEL_W,
  labelGutter,
  isLr,
  isSystem,
  meanSeries,
  ownAxisNames,
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

  test("a group with no points gets no column", () => {
    const rows = points().filter((p) => p.group_id === "base");
    const m = buildCurves(rows, { groups: [{ group_id: "base", label: "base" }, { group_id: "failed", label: "cache r3" }] });
    expect(m.groups.map((g) => g.group_id)).toEqual(["base"]);
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
    // event labels from the server are the tooltips of the marks
    expect(base.querySelector(".event.spike title")?.textContent).toBe("spike 500");
    expect(aug.querySelector(".event.killed title")?.textContent).toBe("killed 600");
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

  test("a non-finite value is drawn like a spike, labelled NaN <step>", () => {
    const meta = {
      ...META,
      events: [{ run_id: "b1", step: 700, kind: "nonfinite" }, ...META.events],
    };
    const { container } = render(<Curves result={result(points(), meta)} />);
    const chart = container.querySelector("svg[role=img]") as SVGElement;
    const base = chart.querySelector('.curve-col[data-group="base"]') as Element;
    const marks = base.querySelectorAll(".event.nonfinite");
    expect(marks.length).toBe(3);
    expect(base.querySelectorAll(".event.nonfinite line.ev").length).toBe(3);
    expect(base.querySelectorAll(".event.nonfinite path.evg").length).toBe(1);
    expect(base.querySelector(".event.nonfinite text.lbl-s")?.textContent).toBe("NaN 700");
    expect(base.querySelector(".event.nonfinite title")?.textContent).toBe("NaN 700");
    // no clip caret: a NaN has no value to point at
    expect(base.querySelectorAll(".event.nonfinite .clip-caret").length).toBe(0);
    // the y-domain is not changed by it
    expect(buildCurves(points(), meta).scales).toEqual(buildCurves(points(), META).scales);
    expect([...container.querySelectorAll(".key span")].map((s) => s.textContent)).toEqual([
      "seed",
      "mean",
      "best ckpt",
      "spike",
      "NaN",
      "killed",
    ]);
  });

  test("a non-finite value after the last finite point stays on the chart", () => {
    const meta = { ...META, events: [{ run_id: "b1", step: 9000, kind: "nonfinite" }] };
    expect(buildCurves(points(), meta).maxStep).toBe(9000);
    // an event of a run with no points (not drawn) never stretches the axis
    const ghost = { ...META, events: [{ run_id: "zz", step: 9000, kind: "nonfinite" }] };
    expect(buildCurves(points(), ghost).maxStep).toBe(1000);
    const { container } = render(<Curves result={result(points(), meta)} />);
    const base = container.querySelector('.curve-col[data-group="base"]') as Element;
    const xs = [...base.querySelectorAll(".event.nonfinite line.ev")].map((l) => Number(l.getAttribute("x1")));
    expect(xs.length).toBeGreaterThan(0);
    // the NaN sits at the right end of the base column, never past it
    const hit = container.querySelector('rect.hit[data-hit="base"]') as Element;
    const x0 = Number(hit.getAttribute("x"));
    const w = Number(hit.getAttribute("width"));
    for (const x of xs) {
      expect(x).toBeGreaterThan(x0 + 0.9 * w);
      expect(x).toBeLessThanOrEqual(x0 + w + 0.5);
    }
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
    const rows = [1, 2, 3, 4].flatMap((i) =>
      [0, 1].map((step) => ({ run_id: `r${i}`, group_id: `g${i}`, seed: 1, name: "loss", step, value: 1 })),
    );
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
    rows: RUNS.flatMap((r) =>
      [0, 1].map((step) => ({ run_id: r.run_id, group_id: r.run_id, seed: r.seed, name: "gpu", step, value: 1 })),
    ),
    meta: { groups },
  });

  test("the server's per-run labels title each column", () => {
    const groups = RUNS.map((r) => ({
      group_id: r.run_id,
      label: `${r.group_id} r${r.seed}`,
      seed_group: r.group_id,
      repeat: r.seed,
    }));
    const { container } = render(<Curves result={perRun(groups)} />);
    const titles = [...container.querySelectorAll("text.ttl")].map((t) => t.textContent);
    expect(titles).toEqual(["base r1", "base r2", "aug r1", "aug r2"]);
  });

  test("repeated labels without run labels get the run's seed", () => {
    const groups = RUNS.map((r) => ({ group_id: r.run_id, label: r.group_id }));
    const model = buildCurves(perRun(groups).rows as unknown as CurvePoint[], { groups });
    expect(model.groups.map((g) => g.label)).toEqual(["base s1", "base s2", "aug s1", "aug s2"]);
  });

  test("a column without a known seed switches the whole label to counters", () => {
    const groups = RUNS.map((r) => ({ group_id: r.run_id, label: r.group_id }));
    const rows = (perRun(groups).rows as unknown as CurvePoint[]).map((p) =>
      p.run_id === "a2" ? { ...p, seed: null } : p,
    );
    const model = buildCurves(rows, { groups });
    expect(model.groups.map((g) => g.label)).toEqual(["base s1", "base s2", "aug #1", "aug #2"]);
  });

  test("unique labels are left alone", () => {
    const model = buildCurves(points(), { groups: [{ group_id: "base", label: "base" }, { group_id: "aug", label: "+aug" }] });
    expect(model.groups.map((g) => g.label)).toEqual(["base", "+aug"]);
  });
});

test("the label gutter widens so a long metric name clears its tick labels", () => {
  const short = buildCurves(points(), undefined);
  expect(labelGutter(short)).toBeGreaterThanOrEqual(LABEL_W);
  expect(labelGutter(short)).toBeLessThan(120);
  const long = buildCurves(
    points().map((p) => ({ ...p, name: p.name === "train_loss" ? "latency_p95_ms_rolling" : p.name })),
    undefined,
  );
  // 22 chars at 12 px (~148 px) plus the tick labels and gaps
  expect(labelGutter(long)).toBeGreaterThan(170);
  expect(labelGutter(long)).toBeLessThanOrEqual(220);
});

test("a metric on a far different step range gets its own axis below the others", () => {
  expect(ownAxisNames({ cpu: 40, gpu: 38, mem: 40, "sweep/rps": 128 })).toEqual(["sweep/rps"]);
  expect(ownAxisNames({ loss: 20000, top1: 20000, lr: 20000 })).toEqual([]);
  expect(ownAxisNames({ only: 5 })).toEqual([]);
  const rows: CurvePoint[] = [];
  for (let s = 0; s <= 40; s += 10) {
    rows.push({ run_id: "r", group_id: "g", seed: 1, name: "cpu", step: s, value: 50 + s });
    rows.push({ run_id: "r", group_id: "g", seed: 1, name: "gpu", step: s, value: 60 });
  }
  for (const c of [1, 16, 64, 128]) rows.push({ run_id: "r", group_id: "g", seed: 1, name: "sweep/rps", step: c, value: c * 2 });
  const model = buildCurves(rows, { groups: [{ group_id: "g", label: "g" }] });
  expect(model.names).toEqual(["cpu", "gpu", "sweep/rps"]);
  expect(model.ownAxis).toEqual(["sweep/rps"]);
  expect(model.maxStep).toBe(40);
  const { container } = render(<Curves result={result(rows, { groups: [{ group_id: "g", label: "g" }] })} />);
  // shared axis (0..40) under gpu, the last shared row; the sweep's own axis (0..128) at the bottom
  const tickTexts = [...container.querySelectorAll("text.tk")].map((t) => t.textContent);
  expect(tickTexts).toContain("40");
  expect(tickTexts).toContain("100");
});

test("the hover crosshair uses each row's own x scale on own-axis rows", () => {
  const rows: CurvePoint[] = [];
  for (let s = 0; s <= 40; s += 10) {
    rows.push({ run_id: "r", group_id: "g", seed: 1, name: "cpu", step: s, value: 50 + s });
    rows.push({ run_id: "r", group_id: "g", seed: 1, name: "gpu", step: s, value: 60 });
  }
  for (const c of [1, 16, 64, 128]) rows.push({ run_id: "r", group_id: "g", seed: 1, name: "sweep/rps", step: c, value: c * 2 });
  const meta = { groups: [{ group_id: "g", label: "g" }] };
  const { container } = render(<Curves result={result(rows, meta)} />);
  // one column at the fallback width 960: x0 = gutter, colW = 960 - gutter
  const x0 = labelGutter(buildCurves(rows, meta));
  const colW = 960 - x0;
  // a quarter across: step 10 of 0..40 on the shared rows, 32 -> nearest 16 of 0..128 on the sweep
  fireEvent.mouseMove(container.querySelector('rect.hit[data-hit="g"]') as Element, { clientX: x0 + colW / 4 });
  const xAt = (row: string) => Number(container.querySelector(`line.xh[data-row="${row}"]`)?.getAttribute("x1"));
  expect(xAt("cpu")).toBeCloseTo(x0 + colW * (10 / 40), 6);
  expect(xAt("gpu")).toBeCloseTo(x0 + colW * (10 / 40), 6);
  expect(xAt("sweep/rps")).toBeCloseTo(x0 + colW * (16 / 128), 6);
  const lines = screen.getByRole("tooltip").textContent?.split("\n") ?? [];
  expect(lines[0]).toBe("g, step 10");
  expect(lines[3]).toBe("sweep/rps (step 16)  s1 32  mean 32");
});

test("a series with a single point next to a longer one is drawn as a dot", () => {
  const rows: CurvePoint[] = [
    { run_id: "a", group_id: "a", seed: 1, name: "train_accuracy", step: 0, value: 0.9 },
    { run_id: "a", group_id: "a", seed: 1, name: "train_accuracy", step: 10, value: 0.95 },
    { run_id: "b", group_id: "b", seed: 1, name: "train_accuracy", step: 0, value: 0.97 },
  ];
  const { container } = render(<Curves result={result(rows, {})} />);
  expect(container.querySelectorAll("circle[data-dot]").length).toBe(1);
  expect(container.querySelector("dl.stats")).toBeNull();
});

describe("a metric with fewer than 2 points is a value, not a curve (UI-F11)", () => {
  const one = (name: string, value: number, run = "r", group = "g", seed = 1): CurvePoint => ({
    run_id: run,
    group_id: group,
    seed,
    name,
    step: 0,
    value,
  });

  test("the model lists it under values, out of the rows and their step axes", () => {
    const rows: CurvePoint[] = [one("train_accuracy", 0.97)];
    for (let s = 0; s <= 40; s += 10) rows.push({ ...one("loss", 1 / (s + 1)), step: s });
    const model = buildCurves(rows, {});
    expect(model.names).toEqual(["loss"]);
    expect(model.values).toEqual(["train_accuracy"]);
    expect(model.ownAxis).toEqual([]);
    expect(model.maxStep).toBe(40);
  });

  test("a run with one logged value shows the value, with no 0-1 step axis", () => {
    const { container } = render(<Curves result={result([one("train_accuracy", 0.9222)], {})} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.queryByText("No metric history yet")).toBeNull();
    const stat = container.querySelector("dl.stats > div");
    expect(stat?.querySelector("dt")?.textContent).toBe("train_accuracy");
    expect(stat?.querySelector("dd")?.textContent).toBe("0.922");
  });

  test("seeds give the mean; several groups each get their own value", () => {
    const rows = [
      one("acc", 0.8, "a1", "a", 1),
      one("acc", 0.9, "a2", "a", 2),
      one("acc", 0.5, "b1", "b", 1),
    ];
    const { container } = render(
      <Curves result={result(rows, { groups: [{ group_id: "a", label: "svm" }, { group_id: "b", label: "rf" }] })} />,
    );
    const stats = [...container.querySelectorAll("dl.stats > div")].map((d) => [
      d.querySelector("dt")?.textContent,
      d.querySelector("dd")?.textContent,
      d.getAttribute("title"),
    ]);
    expect(stats).toEqual([
      ["acc svm", "0.85", "s1 0.8  s2 0.9"],
      ["acc rf", "0.5", "s1 0.5"],
    ]);
  });
});

test("rows follow meta.metrics; system metrics go below the model's, lr last", () => {
  expect(isSystem("sys/gpu_util")).toBe(true);
  expect(isSystem("system.mem")).toBe(true);
  expect(isSystem("sysadmin_score")).toBe(false);
  const names = ["sys/gpu_mem_gb", "sys/gpu_util", "lr", "train/loss", "val/loss", "val/top1"];
  const rows: CurvePoint[] = names.flatMap((name) =>
    [0, 1].map((step) => ({ run_id: "r", group_id: "g", seed: 1, name, step, value: 0.5 })),
  );
  expect(buildCurves(rows, {}).names).toEqual(["train/loss", "val/loss", "val/top1", "sys/gpu_mem_gb", "sys/gpu_util", "lr"]);
  const listed = buildCurves(rows, { metrics: ["val/top1", "train/loss", "val/loss", "lr"] }).names;
  expect(listed.slice(0, 3)).toEqual(["val/top1", "train/loss", "val/loss"]);
});
