import { describe, expect, test } from "bun:test";
import { type CurvePoint, curveSeries, hasTime, matchesSearch, metricSections, stepCurvesBody, stepMetrics, xOf } from "../../src/task/stepMetrics";
import { listIdentities, parseSelection } from "../../src/task/useRunSelection";
import { makeTaskRuns } from "./fixtures";

const sel = parseSelection(new URLSearchParams(), { sortDir: "desc" });
const colorOf = (id: string) => `color-${id}`;
const pt = (run_id: string, step: number, value: number, t?: number, name = "loss"): CurvePoint => ({
  run_id,
  group_id: "g",
  seed: 1,
  name,
  step,
  value,
  ...(t === undefined ? {} : { t }),
});
const POINTS: CurvePoint[] = [pt("run-a1", 0, 2, 100), pt("run-a1", 10, 1, 160), pt("run-a2", 0, 4), pt("run-a2", 5, 3), pt("run-a2", 10, 2), pt("run-a1", 10, 9, 160, "acc"), pt("run-b1", 5, Number.NaN)];

describe("sections and search", () => {
  test("step metrics leave out sweep/* and the step counter", () => {
    expect(stepMetrics(["train/loss", "sweep/lr", "step", "val/top1"])).toEqual(["train/loss", "val/top1"]);
  });

  test("one section per first `/` prefix, first-seen order; names without a prefix go to metrics", () => {
    expect(metricSections(["train/loss", "val/loss", "lr", "train/acc", "sys/gpu"])).toEqual([
      { title: "train", metrics: ["train/loss", "train/acc"] },
      { title: "val", metrics: ["val/loss"] },
      { title: "metrics", metrics: ["lr"] },
      { title: "sys", metrics: ["sys/gpu"] },
    ]);
  });

  test("panel search is a case-insensitive substring; empty matches all", () => {
    expect(matchesSearch("val/Loss", "LOSS")).toBe(true);
    expect(matchesSearch("val/top1", " loss ")).toBe(false);
    expect(matchesSearch("anything", "  ")).toBe(true);
  });

  test("the curves query chunks at 100 metrics and needs both metrics and runs", () => {
    const names = Array.from({ length: 150 }, (_, i) => `m/${i}`);
    const body = stepCurvesBody(names, ["r1"]);
    expect(body?.view?.panels?.map((p) => p.data?.metrics?.length)).toEqual([100, 50]);
    expect(body?.view?.panels?.[0]?.data).toMatchObject({ group_by: "group", max_points: 300, filter: { run_id: ["r1"] } });
    expect(stepCurvesBody(names, [])).toBeNull();
    expect(stepCurvesBody([], ["r1"])).toBeNull();
  });
});

describe("series", () => {
  const groups = listIdentities(sel, makeTaskRuns());

  test("mean over seeds on the union of steps, interpolating each seed", () => {
    const [a] = curveSeries(POINTS, "loss", groups, colorOf, "mean", "step");
    expect(a).toEqual({ id: "g-a", name: "lr 3e-4 · beam 10", color: "color-g-a", points: [[0, 3], [5, 2.25], [10, 1.5]], running: false, failed: false });
    expect(a?.band).toBeUndefined();
  });

  test("mean + band: one series with the min..max band where two or more seeds have a value", () => {
    expect(curveSeries(POINTS, "loss", groups, colorOf, "band", "step")).toEqual([
      {
        id: "g-a",
        name: "lr 3e-4 · beam 10",
        color: "color-g-a",
        points: [[0, 3], [5, 2.25], [10, 1.5]],
        band: [[0, 2, 4], [5, 1.5, 3], [10, 1, 2]],
        running: false,
        failed: false,
      },
    ]);
  });

  test("each seed: one line per run in the identity's colour, grouped by the identity; configs without points draw nothing", () => {
    const series = curveSeries(POINTS, "loss", groups, colorOf, "each", "step");
    expect(series.map((s) => [s.id, s.groupId, s.name, s.color])).toEqual([
      ["g-a:run-a1", "g-a", "lr 3e-4 · beam 10 · seed 1", "color-g-a"],
      ["g-a:run-a2", "g-a", "lr 3e-4 · beam 10 · seed 2", "color-g-a"],
    ]);
  });

  test("each run identity draws its own line; NaN values are skipped", () => {
    const runs = listIdentities({ ...sel, group: "run" }, makeTaskRuns());
    const series = curveSeries(POINTS, "loss", runs, colorOf, "mean", "step");
    expect(series.map((s) => s.id)).toEqual(["run-a1", "run-a2"]);
    expect(series[0]?.name).toBe("lr 3e-4 · beam 10 · seed 1");
  });

  test("wall and relative time use t and drop points without it", () => {
    expect(xOf(pt("r", 3, 1, 50), "wall", 40)).toBe(50);
    expect(xOf(pt("r", 3, 1, 50), "relative", 40)).toBe(10);
    expect(xOf(pt("r", 3, 1), "wall", undefined)).toBeNull();
    expect(xOf(pt("r", 3, 1), "step", undefined)).toBe(3);
    const runs = listIdentities({ ...sel, group: "run" }, makeTaskRuns());
    const series = curveSeries(POINTS, "loss", runs, colorOf, "mean", "relative");
    expect(series.map((s) => [s.id, s.points])).toEqual([["run-a1", [[0, 2], [60, 1]]]]);
    expect(hasTime(POINTS)).toBe(true);
    expect(hasTime([pt("r", 1, 1)])).toBe(false);
  });
});
