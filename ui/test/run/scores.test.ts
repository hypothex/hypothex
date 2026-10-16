import { describe, expect, test } from "bun:test";
import type { ScoreRecord } from "../../src/api/models";
import { currentVersions, meanSd, rankModel, scoreTiles } from "../../src/run/scores";
import { RUN_RF, RUN_SVM, makeDetail } from "../pages/fixtures";
import { SVM_SIBLINGS, makeTaskRuns } from "./taskRunsFixtures";

const data = makeTaskRuns();
const group = data.runs.filter((r) => r.group_id === data.runs.find((x) => x.run_id === RUN_SVM)?.group_id);
const ctx = { primary: "accuracy/value", higherIsBetter: true, versions: data.metric_versions ?? null, group };
const score = (over: Partial<ScoreRecord>): ScoreRecord => ({
  metric: "accuracy", version: "v1", key: "value", value: 0.5, error: null, source_hash: null, created_at: "2026-09-26T21:03:08Z", ...over,
});

describe("scoreTiles", () => {
  test("primary first and marked; Δ vs the config mean coloured outside one seed sd, muted inside", () => {
    const tiles = scoreTiles(makeDetail().scores, ctx);
    expect(tiles.map((t) => [t.label, t.primary, t.old])).toEqual([["accuracy@v1", true, false], ["macro_f1@v1", false, false]]);
    const [acc, f1] = tiles;
    expect(acc?.delta).toBeCloseTo(0.024815, 5);
    expect(acc?.sd).toBeCloseTo(0.022064, 5);
    expect([acc?.noise, acc?.better]).toEqual([false, true]);
    expect(f1?.delta).toBeCloseTo(0.000651, 5);
    expect([f1?.noise, f1?.better]).toEqual([true, null]);
  });

  test("old versions are marked and have no Δ; a failed score keeps its error; the * key is dropped", () => {
    const scores = [...makeDetail().scores, score({ version: "v0", value: 0.88 }), score({ metric: "f2", error: "boom", value: null }), score({ key: "*", error: "x", value: null })];
    const tiles = scoreTiles(scores, ctx);
    const old = tiles.find((t) => t.label === "accuracy@v0");
    expect([old?.old, old?.delta, old?.primary]).toEqual([true, null, false]);
    expect(tiles.at(-1)?.label).toBe("accuracy@v0");
    expect(tiles.find((t) => t.metric === "f2")?.error).toBe("boom");
    expect(tiles.some((t) => t.id.endsWith("/*"))).toBe(false);
  });

  test("without task versions the newest version per metric is current; a single seed has no Δ", () => {
    expect(currentVersions([score({ version: "v2" }), score({ version: "v10" })], null)).toEqual({ accuracy: "v10" });
    const lone = scoreTiles(makeDetail().scores, { ...ctx, versions: null, group: group.slice(2) });
    expect(lone[0]?.delta).toBeNull();
  });

  test("lower is better: a smaller value than the config mean is better", () => {
    const tiles = scoreTiles(makeDetail().scores, { ...ctx, higherIsBetter: false });
    expect(tiles[0]?.better).toBe(false);
  });

  test("meanSd uses the sample sd and needs two values", () => {
    expect(meanSd([1])).toBeNull();
    expect(meanSd([1, 3])).toEqual({ mean: 2, sd: Math.SQRT2 });
  });
});

describe("rankModel", () => {
  test("this run, its seeds, the other configs and the best band, with a one-line summary", () => {
    const rank = rankModel(data, RUN_SVM, "var(--c1)");
    expect(rank?.summary).toBe("1st of 3 seeds · config is best of 2");
    expect(rank?.band).toEqual([0.874, 0.953]);
    expect(rank?.marks.filter((m) => m.kind === "seed").map((m) => m.value)).toEqual([0.89, 0.88]);
    expect(rank?.marks.filter((m) => m.kind === "other")).toHaveLength(1);
    expect(rank?.marks.at(-1)).toEqual({ kind: "this", value: 0.9222222222222223, color: "var(--c1)" });
    expect(rankModel(data, RUN_RF, "var(--c2)")?.summary).toBe("1st of 3 seeds · config is 2nd of 2");
    expect(rankModel(data, SVM_SIBLINGS[0], "var(--c1)")?.summary).toBe("3rd of 3 seeds · config is best of 2");
  });

  test("an unscored run has no strip", () => {
    const unscored = { ...data, runs: data.runs.map((r) => (r.run_id === RUN_SVM ? { ...r, primary: null } : r)) };
    expect(rankModel(unscored, RUN_SVM, "var(--c1)")).toBeNull();
  });
});
