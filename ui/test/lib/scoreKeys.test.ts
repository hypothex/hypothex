import { describe, expect, test } from "bun:test";
import { sectionsFromKeys, splitKey } from "../../src/lib/scoreKeys";

describe("splitKey", () => {
  test("<prefix>/<dataset>.<model>.<metric>; extra dots stay in the dataset", () => {
    expect(splitKey("reported/test-a.gpt4.top10")).toEqual({ prefix: "reported", dataset: "test-a", model: "gpt4", metric: "top10" });
    expect(splitKey("reported/a.b.c.top1")).toEqual({ prefix: "reported", dataset: "a.b", model: "c", metric: "top1" });
  });

  test("one dot is <dataset>.<metric>; no dot is a bare metric", () => {
    expect(splitKey("reported/all.stored_frac")).toEqual({ prefix: "reported", dataset: "all", model: null, metric: "stored_frac" });
    expect(splitKey("accuracy/accuracy")).toEqual({ prefix: "accuracy", dataset: null, model: null, metric: "accuracy" });
    expect(splitKey("top1")).toEqual({ prefix: "", dataset: null, model: null, metric: "top1" });
  });

  test("hypothex.yaml part names choose which part is which", () => {
    expect(splitKey("reported/gpt4.test-a.top10", ["model", "dataset", "metric"])).toEqual({
      prefix: "reported", dataset: "test-a", model: "gpt4", metric: "top10",
    });
    // split from the right: the first part keeps any extra dots
    expect(splitKey("r/x.y.z", ["dataset", "metric"])).toEqual({ prefix: "r", dataset: "x.y", model: null, metric: "z" });
    // a two-part pattern: the non-metric part is the dataset whatever its name, no model
    expect(splitKey("r/gpt4.top10", ["model", "metric"])).toEqual({ prefix: "r", dataset: "gpt4", model: null, metric: "top10" });
    // three parts with other names: first other part is the dataset, second the model
    expect(splitKey("r/x.y.z", ["a", "b", "metric"])).toEqual({ prefix: "r", dataset: "x", model: "y", metric: "z" });
    expect(splitKey("r/y.x.z", ["model", "bench", "metric"])).toEqual({ prefix: "r", dataset: "x", model: "y", metric: "z" });
  });

  test("with part names, fewer parts than names or an empty part is not split", () => {
    expect(splitKey("r/a.top1", ["dataset", "model", "metric"])).toEqual({ prefix: "r", dataset: null, model: null, metric: "a.top1" });
    expect(splitKey("r/top10", ["bench", "metric"])).toEqual({ prefix: "r", dataset: null, model: null, metric: "top10" });
    expect(splitKey("r/a..top1", ["dataset", "model", "metric"])).toEqual({ prefix: "r", dataset: null, model: null, metric: "a..top1" });
  });
});

describe("sectionsFromKeys", () => {
  test("one section per metric, primary's first; one panel per dataset · model, primary key first", () => {
    const keys = [
      "reported/test-b.gpt4.top10",
      "reported/test-a.gpt4.top1",
      "reported/test-a.gpt4.top10",
      "reported/test-b.gpt4.top1",
      "reported/test-a.gpt4.top1",
    ];
    expect(sectionsFromKeys(keys, "reported/test-b.gpt4.top10")).toEqual([
      {
        metric: "top10",
        panels: [
          { key: "reported/test-b.gpt4.top10", title: "test-b · gpt4" },
          { key: "reported/test-a.gpt4.top10", title: "test-a · gpt4" },
        ],
      },
      {
        metric: "top1",
        panels: [
          { key: "reported/test-a.gpt4.top1", title: "test-a · gpt4" },
          { key: "reported/test-b.gpt4.top1", title: "test-b · gpt4" },
        ],
      },
    ]);
  });

  test("keys without dots form a section per prefix with a panel per key", () => {
    expect(sectionsFromKeys(["reported/x", "reported/y", "other/z"], "reported/y")).toEqual([
      { metric: "reported", panels: [{ key: "reported/y", title: "y" }, { key: "reported/x", title: "x" }] },
      { metric: "other", panels: [{ key: "other/z", title: "z" }] },
    ]);
  });

  test("a primary that is not among the keys leaves first-seen order", () => {
    expect(sectionsFromKeys(["a/d1.m", "a/d1.n"], "zzz").map((s) => s.metric)).toEqual(["m", "n"]);
    expect(sectionsFromKeys([], "a/x")).toEqual([]);
  });
});

describe("sectionsFromKeys with part names", () => {
  test("{metric}.{dataset}: the section is the metric part, the title the dataset", () => {
    const keys = ["r/top1.test-a", "r/top10.test-a", "r/top1.test-b"];
    expect(sectionsFromKeys(keys, "r/top10.test-a", ["metric", "dataset"])).toEqual([
      { metric: "top10", panels: [{ key: "r/top10.test-a", title: "test-a" }] },
      { metric: "top1", panels: [{ key: "r/top1.test-a", title: "test-a" }, { key: "r/top1.test-b", title: "test-b" }] },
    ]);
  });

  test("{model}.{dataset}.{metric}: titles are dataset · model, as splitKey reads them", () => {
    expect(sectionsFromKeys(["r/gpt4.test-b.top1", "r/gpt4.test-a.top1"], "r/gpt4.test-b.top1", ["model", "dataset", "metric"])).toEqual([
      { metric: "top1", panels: [{ key: "r/gpt4.test-b.top1", title: "test-b · gpt4" }, { key: "r/gpt4.test-a.top1", title: "test-a · gpt4" }] },
    ]);
  });

  test("a key the names do not split forms a section of its prefix", () => {
    expect(sectionsFromKeys(["acc/value"], "acc/value", ["dataset", "metric"])).toEqual([{ metric: "acc", panels: [{ key: "acc/value", title: "value" }] }]);
  });
});
