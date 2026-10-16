import { expect, test } from "bun:test";
import { screen } from "@testing-library/react";
import { ScoresSection, bestBand, paretoPoints, scoreRows } from "../../src/task/ScoresSection";
import { listIdentities, parseSelection } from "../../src/task/useRunSelection";
import { renderWithClient } from "../pages/helpers";
import { makeTaskRuns } from "./fixtures";

const sel = parseSelection(new URLSearchParams(), { sortDir: "desc" });
const colorOf = (id: string) => `color-${id}`;

test("score rows: the config mean, its test interval and seed dots; unscored configs keep a row", () => {
  const rows = scoreRows(listIdentities(sel, makeTaskRuns()), colorOf);
  expect(rows.map((r) => [r.id, r.mean, r.lo, r.hi, r.seeds, r.n, r.best])).toEqual([
    ["g-a", 0.911, 0.905, 0.917, [0.912, 0.91], 2, true],
    ["g-b", 0.898, 0.892, 0.904, [0.899, 0.897], 2, false],
    ["g-c", null, null, null, [], 0, false],
  ]);
  const runs = scoreRows(listIdentities({ ...sel, group: "run" }, makeTaskRuns()), colorOf);
  expect(runs[0]).toMatchObject({ id: "run-a1", mean: 0.912, lo: null, hi: null, seeds: [], n: 1, best: false });
});

test("the best band is the best config's test interval", () => {
  expect(bestBand(makeTaskRuns())).toEqual({ lo: 0.905, hi: 0.917 });
  expect(bestBand(makeTaskRuns({ groups: [] }))).toBeNull();
});

test("pareto points: mean GPU-hours per scored identity", () => {
  expect(paretoPoints(listIdentities(sel, makeTaskRuns()), colorOf)).toEqual([
    { id: "g-a", name: "lr 3e-4 · beam 10", color: "color-g-a", x: 1.5, y: 0.911, yLo: 0.905, yHi: 0.917 },
    { id: "g-b", name: "lr 1e-4 · beam 10", color: "color-g-b", x: 1.5, y: 0.898, yLo: 0.892, yHi: 0.904 },
  ]);
});

test("the section hides when the search matches neither panel; no Pareto panel outside training", () => {
  const data = makeTaskRuns();
  const items = listIdentities(sel, data);
  const { unmount } = renderWithClient(<ScoresSection data={data} items={items} colorOf={colorOf} highlight={null} query="gpu" />);
  expect(screen.getByRole("region", { name: "top1 vs GPU-hours" })).toBeTruthy();
  expect(screen.queryByRole("region", { name: "top1" })).toBeNull();
  unmount();
  renderWithClient(<ScoresSection data={{ ...data, kind: "generic" }} items={items} colorOf={colorOf} highlight={null} query="gpu" />);
  expect(screen.queryByRole("region", { name: "Scores" })).toBeNull();
});
