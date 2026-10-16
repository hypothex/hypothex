import { describe, expect, test } from "bun:test";
import {
  type CompareState,
  compareFromRows,
  compareLabels,
  compareModel,
  comparePanelSpec,
  compareRows,
  compareTitle,
  compareTitles,
  defaultCompare,
  rowBest,
  toggleKeepOne,
} from "../../src/task/compareModel";
import { DATASETS, EVAL_PRIMARY, evalValue, makeEvalTaskRuns } from "./fixtures";

const data = makeEvalTaskRuns();
const built = compareModel(data.score_keys, EVAL_PRIMARY, data.key_parts);
if (!built) throw new Error("fixture has no compare model");
const model = built;

describe("model", () => {
  test("datasets, models and metrics in key order; labels; defaults from the primary", () => {
    expect(model.datasets).toEqual([...DATASETS]);
    expect(model.models).toEqual(["model-x", "model-y"]);
    expect(model.metrics).toEqual(["top1", "top10"]);
    expect(model.labels).toEqual({ datasets: "Datasets", model: "Model", metrics: "Metrics" });
    expect(defaultCompare(model, EVAL_PRIMARY, data.key_parts)).toEqual({
      datasets: ["test-a", "test-b", "test-c", "test-d"],
      model: "model-x",
      metrics: ["top10"],
      render: "table",
    });
  });

  test("other prefixes, keys without dots and a single dataset give no compare", () => {
    expect(compareModel(["reported/test-a.model-x.top10", "other/test-b.model-x.top10", "reported/all"], EVAL_PRIMARY, null)).toBeNull();
    const two = compareModel(["reported/test-a.top10", "reported/test-b.top10", "other/test-c.top10"], "reported/test-a.top10", null);
    expect(two?.datasets).toEqual(["test-a", "test-b"]);
    expect(two?.models).toEqual([]);
    if (!two) throw new Error("expected a model");
    expect(defaultCompare(two, "reported/test-a.top10", null).model).toBeNull();
  });

  test("control labels come from the task's key parts", () => {
    expect(compareLabels(["split", "arch", "metric"])).toEqual({ datasets: "Splits", model: "Arch", metrics: "Metrics" });
    expect(compareLabels(["dataset", "metric"])).toEqual({ datasets: "Datasets", model: "Model", metrics: "Metrics" });
    expect(compareLabels(null)).toEqual({ datasets: "Datasets", model: "Model", metrics: "Metrics" });
  });

  test("keep-one toggling: the last selected value stays; added values keep the model's order", () => {
    expect(toggleKeepOne(["test-a"], "test-a", DATASETS)).toEqual(["test-a"]);
    expect(toggleKeepOne(["test-c", "test-a"], "test-b", DATASETS)).toEqual(["test-a", "test-b", "test-c"]);
    expect(toggleKeepOne(["test-a", "test-b"], "test-a", DATASETS)).toEqual(["test-b"]);
  });
});

describe("rows", () => {
  test("one row per metric × dataset; a missing key is null; best only between distinct values", () => {
    const cols = [
      { id: "g-v1", name: "db v1", color: "c1", scores: data.runs[0]?.scores ?? {} },
      { id: "g-v3", name: "db v3", color: "c3", scores: data.runs[2]?.scores ?? {} },
    ];
    const rows = compareRows(model, { datasets: ["test-e", "test-a"], model: "model-y", metrics: ["top1", "top10"], render: "table" }, cols, () => true);
    expect(rows.map((r) => [r.metric, r.dataset, r.values, r.best])).toEqual([
      ["top1", "test-a", [evalValue(0, 0, 1, 0), evalValue(2, 0, 1, 0)], evalValue(2, 0, 1, 0)],
      ["top1", "test-e", [null, evalValue(2, 4, 1, 0)], null],
      ["top10", "test-a", [evalValue(0, 0, 1, 1), evalValue(2, 0, 1, 1)], evalValue(2, 0, 1, 1)],
      ["top10", "test-e", [evalValue(0, 4, 1, 1), evalValue(2, 4, 1, 1)], evalValue(2, 4, 1, 1)],
    ]);
    expect(rowBest([0.5, 0.5], true)).toBeNull();
    expect(rowBest([0.2, 0.4], false)).toBe(0.2);
    expect(rowBest([0.3, null], true)).toBeNull();
  });

  test("each row's best follows the direction of that row's key", () => {
    const cols = [
      { id: "g-v1", name: "db v1", color: "c1", scores: data.runs[0]?.scores ?? {} },
      { id: "g-v3", name: "db v3", color: "c3", scores: data.runs[2]?.scores ?? {} },
    ];
    const higher = (key: string) => !key.endsWith(".top1");
    const rows = compareRows(model, { datasets: ["test-a"], model: "model-x", metrics: ["top1", "top10"], render: "table" }, cols, higher);
    expect(rows.map((r) => [r.metric, r.best])).toEqual([
      ["top1", evalValue(0, 0, 0, 0)],
      ["top10", evalValue(2, 0, 0, 1)],
    ]);
  });

  test("a view panel spec for Save as view, and saved rows back to a model", () => {
    expect(comparePanelSpec({ datasets: ["test-a", "test-b"], model: "model-x", metrics: ["top10"], render: "bars" }, model.labels)).toEqual({
      type: "compare",
      title: "Compare datasets · model-x",
      data: { datasets: ["test-a", "test-b"], model: "model-x", metrics: ["top10"] },
      render: "bars",
    });
    expect(compareTitle({ datasets: ["test-a"], model: null, metrics: ["top10"], render: "table" }, compareLabels(["split", "metric"]))).toBe("Compare splits");
    const x: CompareState = { datasets: ["test-a"], model: "model-x", metrics: ["top10"], render: "table" };
    const y = { ...x, model: "model-y" };
    expect(compareTitles([x, y, { ...x, metrics: ["top1"] }, x], model.labels)).toEqual([
      "Compare datasets · model-x",
      "Compare datasets · model-y",
      "Compare datasets · model-x · 2",
      "Compare datasets · model-x · 3",
    ]);
    expect(comparePanelSpec(x, model.labels, "Compare datasets · model-x · 2").title).toBe("Compare datasets · model-x · 2");
    const back = compareFromRows([
      { dataset: "test-a", model: "model-x", metric: "top10", key: "reported/test-a.model-x.top10", run_id: "run-v1", group_id: "g-v1", name: "db v1", value: 0.7 },
      { dataset: "test-b", model: "model-x", metric: "top10", key: "reported/test-b.model-x.top10", run_id: "run-v1", group_id: "g-v1", name: "db v1", value: 0.65 },
      { dataset: "test-a", model: "model-x", metric: "top10", key: "reported/test-a.model-x.top10", run_id: "run-v3", group_id: "g-v3", name: "db v3", value: 0.9 },
    ]);
    expect(back?.model.datasets).toEqual(["test-a", "test-b"]);
    expect(back?.columns.map((c) => [c.id, c.name, c.scores])).toEqual([
      ["g-v1", "db v1", { "reported/test-a.model-x.top10": 0.7, "reported/test-b.model-x.top10": 0.65 }],
      ["g-v3", "db v3", { "reported/test-a.model-x.top10": 0.9 }],
    ]);
    expect(back?.state).toEqual({ datasets: ["test-a", "test-b"], model: "model-x", metrics: ["top10"] });
    expect(compareFromRows([])).toBeNull();
  });

});
