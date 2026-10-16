import { expect, test } from "bun:test";
import { screen, within } from "@testing-library/react";
import { ScoreKeySections, barRows, visibleKeySections } from "../../src/task/ScoreKeySections";
import { listIdentities, parseSelection } from "../../src/task/useRunSelection";
import { renderWithClient } from "../pages/helpers";
import { EVAL_PRIMARY, makeBenchTaskRuns, makeEvalTaskRuns } from "./fixtures";

const sel = parseSelection(new URLSearchParams(), { sortDir: "desc" });
const colorOf = (id: string) => `color-${id}`;

test("one section per metric, the primary's first with the primary panel first; search matches keys", () => {
  const data = makeEvalTaskRuns();
  const all = visibleKeySections(data, "");
  expect(all.map((s) => s.metric)).toEqual(["top10", "top1"]);
  expect(all.map((s) => s.panels.length)).toEqual([10, 10]);
  expect(all[0]?.panels[0]?.key).toBe(EVAL_PRIMARY);
  expect(visibleKeySections(data, "test-e").map((s) => s.panels.map((p) => p.key))).toEqual([
    ["reported/test-e.model-x.top10", "reported/test-e.model-y.top10"],
    ["reported/test-e.model-x.top1", "reported/test-e.model-y.top1"],
  ]);
  expect(visibleKeySections(data, "no such key")).toEqual([]);
});

test("bar rows: each identity's score, whiskers on the primary only, missing keys are null", () => {
  const data = makeEvalTaskRuns();
  const best = data.groups.find((g) => g.group_id === "g-v3");
  if (!best) throw new Error("fixture");
  best.test_interval = { lo: 0.85, hi: 0.95, method: "wilson", n: 400 };
  const items = listIdentities(sel, data);
  const rows = barRows(items, EVAL_PRIMARY, data, colorOf);
  expect(rows.map((r) => [r.id, r.value, r.best, r.color])).toEqual([
    ["g-v3", 0.9, true, "color-g-v3"],
    ["g-v2", 0.8, false, "color-g-v2"],
    ["g-v1", 0.7, false, "color-g-v1"],
  ]);
  expect(rows[0]?.ci).toEqual({ lo: 0.85, hi: 0.95, method: "wilson" });
  expect(barRows(items, "reported/test-a.model-x.top1", data, colorOf)[0]?.ci).toBeNull();
  expect(barRows(items, "reported/test-e.model-y.top1", data, colorOf).find((r) => r.id === "g-v1")?.value).toBeNull();
});

test("bar rows: the best value of that key is marked, in the task direction when the key's is unknown, never from one value", () => {
  const data = makeEvalTaskRuns();
  const key = "reported/test-b.model-x.top1";
  const v1 = data.groups.find((g) => g.group_id === "g-v1");
  if (!v1) throw new Error("fixture");
  v1.scores = { ...v1.scores, [key]: 0.99 };
  const items = listIdentities(sel, data);
  const bestOf = (k: string, d = data) => barRows(items, k, d, colorOf).filter((r) => r.best).map((r) => r.id);
  expect(bestOf(key)).toEqual(["g-v1"]);
  const lower = { ...data, higher_is_better: false, key_higher_is_better: {} };
  expect(bestOf(EVAL_PRIMARY, lower)).toEqual(["g-v1"]);
  expect(bestOf(key, lower)).toEqual(["g-v2"]);
  // a key's own direction wins over the task's
  expect(bestOf(key, { ...data, higher_is_better: false })).toEqual(["g-v1"]);
  expect(barRows(items.slice(0, 1), key, data, colorOf).some((r) => r.best)).toBe(false);
});

test("sections: the primary's open and marked, the others closed", () => {
  const data = makeEvalTaskRuns();
  renderWithClient(<ScoreKeySections data={data} items={listIdentities(sel, data)} colorOf={colorOf} highlight={null} query="" />);
  const top10 = screen.getByRole("region", { name: "top10" });
  const top1 = screen.getByRole("region", { name: "top1" });
  expect(within(top10).getAllByRole("button", { expanded: true }).length).toBeGreaterThan(0);
  expect(within(top1).getAllByRole("button", { expanded: false }).length).toBeGreaterThan(0);
  expect(within(top10).getByText("★ primary")).toBeTruthy();
});

test("bar rows: each key is marked in its own direction, the task's only when the key's is unknown", () => {
  const data = makeBenchTaskRuns();
  const items = listIdentities(sel, data);
  const bestOf = (k: string) => barRows(items, k, data, colorOf).filter((r) => r.best).map((r) => r.id);
  expect(bestOf("latency/p95")).toEqual(["g-fast"]);
  expect(bestOf("throughput/rps")).toEqual(["g-wide"]);
  expect(bestOf("throughput/peak")).toEqual(["g-fast"]);
});
