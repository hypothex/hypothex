import { expect, test } from "bun:test";
import type { PanelSpec, ViewSpec } from "../../src/api/models";
import { applyOverrides, authoredSeeds, metricOptions } from "../../src/task/viewOverrides";
import { makeBoard } from "../pages/fixtures";

const view = (panels: PanelSpec[]): ViewSpec => ({ title: "v", panels });

test("metricOptions: the primary, then recorded metric/key refs with a known version", () => {
  const board = makeBoard();
  const first = board.rows[0];
  if (!first?.primary) throw new Error("fixture");
  first.scores = { "accuracy/value": first.primary, "macro_f1/value": { ...first.primary, mean: 0.8 }, "ghost/value": first.primary, "accuracy@v1/value": first.primary };
  expect(metricOptions(board)).toEqual(["accuracy/value", "macro_f1/value"]);
});

test("a primary override reaches leaderboard, stat_strip and curves only", () => {
  const scatter: PanelSpec = { type: "scatter", title: "s", data: { x: "usage.usd", y: "accuracy/value" } };
  const out = applyOverrides(
    view([{ type: "leaderboard", title: "l", data: {} }, { type: "stat_strip", title: "s" }, { type: "curves", title: "c", data: { metrics: ["loss"] } }, scatter]),
    { primary: "macro_f1/value" },
  );
  expect(out.panels?.map((p) => p.data?.primary)).toEqual(["macro_f1/value", "macro_f1/value", "macro_f1/value", undefined]);
  expect(out.panels?.[2]?.data?.metrics).toEqual(["loss"]);
  expect(out.panels?.[3]).toEqual(scatter);
});

test("seeds toggle only the seed noise of leaderboard panels; authored noise decides the default", () => {
  const authored = view([{ type: "leaderboard", title: "l", noise: ["test_set"] }, { type: "curves", title: "c", data: { group_by: "config" } }]);
  expect(authoredSeeds(authored)).toBe(false);
  expect(authoredSeeds(view([{ type: "leaderboard", title: "l" }]))).toBe(true);
  expect(authoredSeeds(view([{ type: "stat_strip", title: "s" }]))).toBe(true);
  const on = applyOverrides(authored, { seeds: true });
  expect(on.panels?.[0]?.noise).toEqual(["test_set", "seed"]);
  expect(on.panels?.[1]).toEqual({ type: "curves", title: "c", data: { group_by: "config" } });
  expect(applyOverrides(view([{ type: "leaderboard", title: "l" }]), { seeds: false }).panels?.[0]?.noise).toEqual(["test_set"]);
});
