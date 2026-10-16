import { describe, expect, test } from "bun:test";
import { ApiError } from "../../src/api/client";
import { reevalLine } from "../../src/pages/components/ReevalSummary";
import { boardWarnings, isGone, metricVersions, notFound, parseTab, sameTab, tabParam, taskFacts } from "../../src/task/facts";
import { makeBoard } from "../pages/fixtures";
import { makeTaskRuns } from "./fixtures";

const tab = (q: string) => parseTab(new URLSearchParams(q));

describe("tabs", () => {
  test("?tab= names the tab; unknown values and an empty view are Charts", () => {
    expect(tab("")).toEqual({ kind: "charts" });
    expect(tab("tab=runs")).toEqual({ kind: "runs" });
    expect(tab("tab=sweeps")).toEqual({ kind: "sweeps" });
    expect(tab("tab=examples")).toEqual({ kind: "examples" });
    expect(tab("tab=view%3Aroute-quality")).toEqual({ kind: "view", name: "route-quality" });
    expect(tab("tab=view:")).toEqual({ kind: "charts" });
    expect(tab("tab=nonsense")).toEqual({ kind: "charts" });
  });

  test("a legacy ?view= opens that view; overview is Charts; ?tab= wins", () => {
    expect(tab("view=route-quality")).toEqual({ kind: "view", name: "route-quality" });
    expect(tab("view=overview")).toEqual({ kind: "charts" });
    expect(tab("tab=runs&view=x")).toEqual({ kind: "runs" });
  });

  test("tabParam round-trips and sameTab compares by it", () => {
    expect(tabParam({ kind: "charts" })).toBeNull();
    expect(tabParam({ kind: "runs" })).toBe("runs");
    expect(tabParam({ kind: "view", name: "a" })).toBe("view:a");
    expect(sameTab({ kind: "view", name: "a" }, { kind: "view", name: "a" })).toBe(true);
    expect(sameTab({ kind: "view", name: "a" }, { kind: "view", name: "b" })).toBe(false);
  });
});

describe("facts line", () => {
  test("primary, direction, best config and its best run, counts", () => {
    expect(taskFacts(makeTaskRuns())).toEqual({
      primary: "top1",
      direction: "↑",
      best: { value: 0.911, runId: "run-a1", name: "lr 3e-4 · beam 10" },
      runs: 8,
      configs: 4,
      running: 1,
      queued: 1,
    });
  });

  test("lower is better picks the lowest run of the best config; no best without runs", () => {
    const lower = taskFacts(makeTaskRuns({ higher_is_better: false }));
    expect(lower.direction).toBe("↓");
    expect(lower.best?.runId).toBe("run-a2");
    expect(taskFacts(makeTaskRuns({ runs: [], groups: [] })).best).toBeNull();
  });

  test("board warnings and metric versions", () => {
    expect(boardWarnings({ ...makeBoard(), needs_reeval: ["r1"], unscored: ["u1", "u2"] })).toEqual(["1 need re-eval", "2 unscored"]);
    expect(boardWarnings(makeBoard())).toEqual([]);
    expect(metricVersions(makeBoard())).toBe("accuracy v1, macro_f1 v1");
  });

  test("reevalLine counts re-scored and skipped runs, with each skip reason", () => {
    expect(reevalLine({ evaluated: ["a", "b"], skipped: {}, warnings: [] })).toBe("2 re-scored");
    expect(
      reevalLine({ evaluated: ["a"], skipped: { b: "no predictions", c: "no predictions", d: "metric failed" }, warnings: ["w1", "w2"] }),
    ).toBe("1 re-scored · 3 skipped: no predictions ×2, metric failed ×1 · 2 warnings");
    expect(reevalLine({} as never)).toBe("0 re-scored");
  });
});

describe("not found", () => {
  const err = (status: number, type: string, message: string) => new ApiError(status, message, type, [], null);
  test("404 and 400 unknown task are gone; other errors are not", () => {
    expect(isGone(err(404, "StoreError", "unknown project 'nope'"))).toBe(true);
    expect(isGone(err(400, "ConfigError", "unknown task 'nope' in project 'p'"))).toBe(true);
    expect(isGone(err(400, "ConfigError", "bad metric 'x'"))).toBe(false);
    expect(isGone(err(500, "StoreError", "index locked"))).toBe(false);
    expect(isGone(null)).toBe(false);
    const gone = err(404, "StoreError", "x");
    expect(notFound(null, err(500, "StoreError", "y"), gone)).toBe(gone);
  });
});
