import { expect, test } from "bun:test";
import type { MetricPoint } from "../../src/api/models";
import { curveSeries, pickCurves } from "../../src/run/curves";
import { metricSections, stepMetrics } from "../../src/task/stepMetrics";

test("stepMetrics leaves out sweep/* and the step counter", () => {
  expect(stepMetrics(["train/loss", "sweep/p95", "step", "lr"])).toEqual(["train/loss", "lr"]);
});

test("pickCurves: the primary's metric first, then losses, then the rest, at most three", () => {
  expect(pickCurves(["lr", "train/loss", "val/top1", "val/loss", "gpu"], "top1/value")).toEqual(["val/top1", "train/loss", "val/loss"]);
  expect(pickCurves(["a", "b"], null)).toEqual(["a", "b"]);
});

test("metricSections group by the first / prefix; bare names go to metrics", () => {
  expect(metricSections(["train/loss", "lr", "val/top1", "train/acc"])).toEqual([
    { title: "train", metrics: ["train/loss", "train/acc"] },
    { title: "metrics", metrics: ["lr"] },
    { title: "val", metrics: ["val/top1"] },
  ]);
});

test("curveSeries: this run in its colour and drawn last, seeds grey and faint", () => {
  const p = (name: string, step: number, value: number): MetricPoint => ({ name, step, value, t: null });
  const byRun = new Map([["me", [p("loss", 0, 2), p("loss", 1, 1), p("lr", 0, 1)]], ["s1", [p("loss", 0, 3)]], ["s2", [p("lr", 0, 1)]]]);
  const labels = new Map([["me", "this run"], ["s1", "seed 1"]]);
  expect(curveSeries(byRun, "loss", "me", "var(--c1)", labels)).toEqual([
    { id: "s1", name: "seed 1", color: "var(--c0)", points: [[0, 3]], bold: false, faint: true },
    { id: "me", name: "this run", color: "var(--c1)", points: [[0, 2], [1, 1]], bold: true, faint: false },
  ]);
});
