import { describe, expect, test } from "bun:test";
import type { SweepSpec } from "../../src/api/models";
import { type SweepCellRow, parseCells } from "../../src/pages/components/SweepModel";
import { SCORE_AXIS, bestComparison, parallelAxes, sweepLines, taskSweepIds, whatMatters } from "../../src/task/sweepMath";
import { RAW_CELLS } from "../pages/sweepFixtures";
import { makeTaskRuns } from "./fixtures";

const cell = (lr: string, beam: string, mean: number | null, n: number, std: number | null): SweepCellRow => ({
  params: { lr, beam },
  group_id: null,
  n,
  uncounted: 0,
  mean,
  lo: null,
  hi: null,
  std,
  run_ids: [],
  runs: [],
});

const SPEC: SweepSpec = {
  id: "s-1",
  project: "toy-proj",
  task: "toy-task",
  host: null,
  grid: [
    { name: "lr", values: ["1e-4", "3e-4"], low: null, high: null, log: false },
    { name: "beam", values: ["10"], low: null, high: null, log: false },
  ],
  random: null,
  seeds: [1, 2],
  command_template: [],
  created_by: "agent:tuner",
  created_at: "2026-10-03T09:00:00Z",
};

describe("what matters", () => {
  test("balanced 2×2 grid: main-effect shares and the seed share", () => {
    const out = whatMatters(
      [cell("a", "1", 0.8, 2, 0.01), cell("a", "2", 0.82, 2, 0.01), cell("b", "1", 0.9, 2, 0.01), cell("b", "2", 0.92, 2, 0.01)],
      ["lr", "beam"],
    );
    expect(out.map((x) => x.name)).toEqual(["lr", "beam", "seed"]);
    expect(out[0]?.share).toBeCloseTo(0.02 / 0.0212, 6);
    expect(out[1]?.share).toBeCloseTo(0.0008 / 0.0212, 6);
    expect(out[2]?.share).toBeCloseTo(0.0004 / 0.0212, 6);
  });

  test("a pure interaction shows as interaction, not as either param", () => {
    const out = whatMatters([cell("a", "1", 0.8, 1, null), cell("a", "2", 0.9, 1, null), cell("b", "1", 0.9, 1, null), cell("b", "2", 0.8, 1, null)], ["lr", "beam"]);
    expect(out.map((x) => [x.name, Number(x.share.toFixed(6))])).toEqual([["lr", 0], ["beam", 0], ["interaction", 1], ["seed", 0]]);
  });

  test("nothing scored, or no variance at all: no rows", () => {
    expect(whatMatters([cell("a", "1", null, 0, null)], ["lr"])).toEqual([]);
    expect(whatMatters([cell("a", "1", 0.5, 1, null), cell("b", "1", 0.5, 1, null)], ["lr"])).toEqual([]);
  });
});

describe("best cell and lines", () => {
  test("best against the next cell: delta and whether the intervals overlap", () => {
    const cmp = bestComparison(parseCells(RAW_CELLS), true);
    expect(cmp?.best.params).toEqual({ lr: "3e-4", beam: "10" });
    expect(cmp?.next?.params).toEqual({ lr: "3e-4", beam: "5" });
    expect(cmp?.delta).toBeCloseTo(0.008, 10);
    expect(cmp?.overlap).toBe(true);
    expect(bestComparison([cell("a", "1", null, 0, null)], true)).toBeNull();
    expect(bestComparison([cell("a", "1", 0.5, 1, null)], true)).toMatchObject({ next: null, delta: null, overlap: null });
  });


  test("one line per scored sweep run; axes from the grid, then the score", () => {
    const data = makeTaskRuns();
    data.runs = data.runs.map((r) => (["run-a1", "run-a2", "run-b1", "run-c1"].includes(r.run_id) ? { ...r, sweep_id: "s-1" } : r));
    const lines = sweepLines(data, SPEC);
    expect(lines.map((l) => [l.id, l.values])).toEqual([
      ["run-a1", { [SCORE_AXIS]: 0.912, lr: "3e-4", beam: "10" }],
      ["run-a2", { [SCORE_AXIS]: 0.91, lr: "3e-4", beam: "10" }],
      ["run-b1", { [SCORE_AXIS]: 0.899, lr: "1e-4", beam: "10" }],
    ]);
    expect(lines[2]?.name).toBe("lr 1e-4 · beam 10 · seed 1");
    expect(parallelAxes(SPEC, "top1")).toEqual([
      { key: "lr", label: "lr", values: ["1e-4", "3e-4"] },
      { key: "beam", label: "beam", values: ["10"] },
      { key: SCORE_AXIS, label: "top1" },
    ]);
  });

  test("the task's sweeps, newest run first", () => {
    const data = makeTaskRuns();
    data.runs = data.runs.map((r, i) => ({ ...r, sweep_id: i < 3 ? "s-new" : i < 5 ? "s-old" : null }));
    expect(taskSweepIds(data)).toEqual(["s-new", "s-old"]);
    expect(taskSweepIds(makeTaskRuns())).toEqual([]);
  });
});
