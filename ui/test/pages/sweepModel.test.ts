import { describe, expect, test } from "bun:test";
import type { HostRow, RunRecord, SweepParam, SweepSpec } from "../../src/api/models";
import {
  type SweepCellRow,
  cellLabel,
  cellTip,
  fmtAge,
  gridLabel,
  heatAxes,
  heatLevel,
  heatPercent,
  hostOf,
  hostsOf,
  meanOf,
  orderRuns,
  paramsText,
  parseCell,
  parseCells,
  rankCells,
  runState,
  sameParams,
  seedValues,
  staleHosts,
  stateText,
  sweepHref,
} from "../../src/pages/components/SweepModel";
import { CELL_D, HOSTS, NOW, RAW_CELLS, RUNS, STALE, makeSummary, makeSweepBoard, rid, run } from "./sweepFixtures";
import { fmtAgeMs } from "../../src/pages/components/HostsPanel";

const SPEC: SweepSpec = makeSummary().spec;
const NAMES = ["lr", "beam"];
const cells = (): SweepCellRow[] => parseCells(RAW_CELLS);
const param = (
  name: string,
  values: string[] | null,
  low: number | null = null,
  high: number | null = null,
  log = false,
): SweepParam => ({ name, values, low, high, log });

describe("parseCells", () => {
  test("turns summary cells into typed rows", () => {
    expect(cells()).toHaveLength(4);
    expect(cells()[0]).toEqual({
      params: { lr: "1e-4", beam: "5" },
      group_id: "g-1e-4-5",
      n: 1,
      uncounted: 0,
      mean: 0.89,
      lo: 0.885,
      hi: 0.895,
      std: null,
      run_ids: [rid("a1"), rid("a2")],
      runs: [
        { run_id: rid("a1"), status: "finished", seed: 1 },
        { run_id: rid("a2"), status: "queued", seed: 2 },
      ],
    });
    expect(sameParams(cells()[3]?.params ?? {}, { beam: "10", lr: "3e-4" })).toBe(true);
    expect(sameParams({ lr: "3e-4" }, { lr: "3e-4", beam: "10" })).toBe(false);
  });

  test("keeps a cell without runs or stats and drops junk", () => {
    expect(parseCell(null)).toBeNull();
    expect(parseCell({})).toBeNull();
    expect(parseCell([1, 2])).toBeNull();
    expect(parseCell({ params: { lr: 0.001 }, run_ids: ["x"] })).toEqual({
      params: { lr: "0.001" },
      group_id: null,
      n: 0,
      uncounted: 0,
      mean: null,
      lo: null,
      hi: null,
      std: null,
      run_ids: ["x"],
      runs: [{ run_id: "x", status: null, seed: null }],
    });
    expect(parseCells([null, RAW_CELLS[0], "junk"])).toHaveLength(1);
  });

  test("an unknown run status becomes null and a run without id is dropped", () => {
    const parsed = parseCell({ params: {}, runs: [{ run_id: "x", status: "paused", seed: 3 }, { status: "queued" }] });
    expect(parsed?.runs).toEqual([{ run_id: "x", status: null, seed: 3 }]);
    expect(parsed?.run_ids).toEqual(["x"]);
  });
});

describe("run state", () => {
  test("a queued or running run on a host that is not connected is stale; other states pass through", () => {
    expect(staleHosts(HOSTS)).toEqual(new Map([["env-dgx", "2026-10-03T11:56:00Z"]]));
    expect(staleHosts(undefined).size).toBe(0);
    // every state but connected counts; a host that never connected has no environment yet
    const [gpu1] = HOSTS as [HostRow];
    const off: HostRow = {
      ...gpu1,
      name: "gpu3",
      state: { ...gpu1.state, name: "gpu3", state: "disabled", since: "2026-10-03T10:00:00Z", environment_id: "env-gpu3" },
    };
    const fresh: HostRow = { ...gpu1, name: "gpu4", state: { ...gpu1.state, name: "gpu4", state: "connecting", environment_id: null } };
    expect(staleHosts([...HOSTS, off, fresh])).toEqual(
      new Map([
        ["env-dgx", "2026-10-03T11:56:00Z"],
        ["env-gpu3", "2026-10-03T10:00:00Z"],
      ]),
    );
    expect(runState(run("b2"), null, STALE)).toBe("stale");
    expect(runState(run("b2"), null, new Map())).toBe("running");
    expect(runState(run("d1"), null, STALE)).toBe("finished");
    expect(runState(run("a2"), "finished", STALE)).toBe("queued");
    // a queued run on a host that is not connected is stale too, as its run page says
    expect(runState({ ...run("a2"), environment_id: "env-dgx" }, null, STALE)).toBe("stale");
    // matched by environment, not by executor.host (the box's own hostname)
    expect(runState({ ...run("b2"), environment_id: "env-gpu1" }, null, STALE)).toBe("running");
    // listed by the summary but not mirrored yet: the cell's status, else queued
    expect(runState(undefined, "running", STALE)).toBe("running");
    expect(runState(undefined, null, STALE)).toBe("queued");
  });

  test("stateText names the stale age, queue position, SLURM job, node and exit code", () => {
    expect(stateText(run("b2"), "stale", STALE, NOW)).toBe("stale 4m");
    expect(stateText(run("a2"), "queued", STALE, NOW)).toBe("queued, pos 2");
    expect(stateText(run("c2"), "failed", STALE, NOW)).toBe("failed, exit 1");
    expect(stateText(run("d1"), "finished", STALE, NOW)).toBe("finished");
    const b2 = run("b2");
    const slurm: RunRecord = {
      ...b2,
      executor: { ...b2.executor, slurm_job_id: "48211", node: "c0412", queue_position: null },
    };
    expect(stateText(slurm, "running", STALE, NOW)).toBe("running, c0412");
    expect(stateText({ ...slurm, status: "queued" }, "queued", STALE, NOW)).toBe("queued, job 48211");
    expect(stateText(run("b2"), "stale", new Map(), NOW)).toBe("stale");
    expect(stateText({ ...run("a2"), environment_id: "env-dgx" }, "stale", STALE, NOW)).toBe("stale 4m");
  });

  test("the stale age uses the host row's short age: 90 min reads 1h, 2 days read 2d", () => {
    const since = (ms: number): Map<string, string> => new Map([["env-dgx", new Date(NOW - ms).toISOString()]]);
    const r = { ...run("a2"), environment_id: "env-dgx" };
    expect(stateText(r, "stale", since(5_400_000), NOW)).toBe(`stale ${fmtAgeMs(5_400_000)}`);
    expect(stateText(r, "stale", since(5_400_000), NOW)).toBe("stale 1h");
    expect(stateText(r, "stale", since(172_800_000), NOW)).toBe("stale 2d");
    expect(stateText(r, "stale", since(-5_000), NOW)).toBe("stale 0s");
  });

  test("fmtAge prints a duration in seconds as seconds, minutes, or hours and minutes", () => {
    expect([fmtAge(42), fmtAge(240), fmtAge(5400), fmtAge(6720), fmtAge(-5)]).toEqual([
      "42s",
      "4m",
      "1h 30m",
      "1h 52m",
      "0s",
    ]);
  });
});

describe("axes, ranking and heat", () => {
  test("two list params give heat axes in grid order", () => {
    expect(heatAxes(SPEC)).toEqual({ row: "lr", col: "beam", rows: ["1e-4", "3e-4"], cols: ["5", "10"] });
  });

  test("one, three, or sampled params fall back to the table", () => {
    expect(heatAxes({ ...SPEC, grid: [param("lr", ["1e-4"])] })).toBeNull();
    expect(heatAxes({ ...SPEC, grid: [param("lr", ["1e-4"]), param("beam", ["5"]), param("wd", ["0"])] })).toBeNull();
    expect(heatAxes({ ...SPEC, grid: [param("lr", null, 1e-5, 1e-2, true), param("beam", ["5"])] })).toBeNull();
  });

  test("rankCells puts the best scored cell first in the metric's direction", () => {
    const labels = (cs: SweepCellRow[]): string[] => cs.map((c) => cellLabel(c.params, NAMES));
    const withEmpty = [...cells(), parseCell({ params: { lr: "1e-3", beam: "5" }, run_ids: [] }) as SweepCellRow];
    expect(labels(rankCells(withEmpty, true))).toEqual(["3e-4, 10", "3e-4, 5", "1e-4, 10", "1e-4, 5"]);
    expect(labels(rankCells(withEmpty, false))).toEqual(["1e-4, 5", "1e-4, 10", "3e-4, 5", "3e-4, 10"]);
  });

  test("heatLevel is 1 at the best end; heatPercent maps 0..1 to 4..34", () => {
    expect(heatLevel(0.912, 0.89, 0.912, true)).toBe(1);
    expect(heatLevel(0.89, 0.89, 0.912, true)).toBe(0);
    expect(heatLevel(0.89, 0.89, 0.912, false)).toBe(1);
    expect(heatLevel(0.5, 0.5, 0.5, true)).toBe(1);
    expect([heatPercent(0), heatPercent(0.5), heatPercent(1)]).toEqual([4, 19, 34]);
  });
});

describe("labels", () => {
  test("cell, params and grid labels", () => {
    const d = parseCell(CELL_D) as SweepCellRow;
    expect(cellLabel(d.params, NAMES)).toBe("3e-4, 10");
    expect(cellLabel({ lr: "3e-4" }, NAMES)).toBe("3e-4, —");
    expect(paramsText(d.params, NAMES)).toBe("lr 3e-4, beam 10");
    expect(gridLabel(SPEC)).toBe("lr 2 × beam 2 × 2 seeds");
  });

  test("gridLabel shows sampled ranges and the sample count", () => {
    const spec: SweepSpec = {
      ...SPEC,
      grid: [param("lr", null, 0.00001, 0.01, true), param("beam", ["5", "10"])],
      random: 8,
      seeds: [1],
    };
    expect(gridLabel(spec)).toBe("lr 0.00001–0.01 log × beam 2 × 8 samples × 1 seed");
  });

  test("cellTip lists mean, seeds, interval and seed spread", () => {
    const d = parseCell(CELL_D) as SweepCellRow;
    expect(cellTip(d, NAMES, [0.911, 0.913])).toBe(
      "lr 3e-4, beam 10\nmean 0.9120 over 2 seeds\nseeds 0.9110, 0.9130\n95% CI 0.9080–0.9160\nseed σ 0.0014",
    );
    const a = cells()[0] as SweepCellRow;
    expect(cellTip(a, NAMES, [])).toBe("lr 1e-4, beam 5\nmean 0.8900 over 1 seed\n95% CI 0.8850–0.8950");
    const empty = parseCell({ params: { lr: "1e-3", beam: "5" }, run_ids: ["x"] }) as SweepCellRow;
    expect(cellTip(empty, NAMES, [])).toBe("lr 1e-3, beam 5\nno scored runs yet");
  });

  test("meanOf skips gaps; seedValues reads the cell's leaderboard row", () => {
    expect(meanOf([0.89, null, 0.9])).toBeCloseTo(0.895, 10);
    expect(meanOf([null])).toBeNull();
    const board = makeSweepBoard();
    const d = parseCell(CELL_D) as SweepCellRow;
    expect(seedValues(d, board)).toEqual([0.911, 0.913]);
    expect(seedValues(d, undefined)).toEqual([]);
    expect(seedValues(parseCell({ params: {}, run_ids: [] }) as SweepCellRow, board)).toEqual([]);
    // cell A has a1 and a2; its group's row holds a1 only: those are the cell's own runs
    expect(seedValues(parseCell(RAW_CELLS[0]) as SweepCellRow, board)).toEqual([0.89]);
  });

  test("seedValues gives no dots when the task's group also holds runs outside the cell", () => {
    // the same config ran before the sweep: the task leaderboard row mixes those seeds in,
    // while the cell's mean and 95% CI cover the sweep's runs only
    const board = makeSweepBoard();
    const d = parseCell(CELL_D) as SweepCellRow;
    const mixed = {
      ...board,
      rows: board.rows.map((r) =>
        r.group_id === d.group_id
          ? { ...r, run_ids: [...r.run_ids, "20261001-000000-fwd-zz"], seed_values: { "top1/value": [0.911, 0.913, 0.95] } }
          : r,
      ),
    };
    expect(seedValues(d, mixed)).toEqual([]);
  });
});

describe("runs and links", () => {
  test("orderRuns follows the sweep's run ids; hostsOf lists hosts once, in that order", () => {
    const ids = makeSummary().run_ids;
    const ordered = orderRuns([...RUNS].reverse(), ids);
    expect(ordered.map((r) => r.run_id)).toEqual(ids);
    const extra: RunRecord = { ...run("a1"), run_id: "zz-extra" };
    expect(orderRuns([extra, ...RUNS], ids).at(-1)?.run_id).toBe("zz-extra");
    expect(hostsOf(ordered, HOSTS)).toEqual(["gpu1", "dgx"]);
    // without the hosts list: the machines' own hostnames
    expect(hostsOf(ordered, undefined)).toEqual(["sv-a100-01", "dgx-h100-07"]);
  });

  test("hostOf names the hub's host serving the run's environment, never executor.host", () => {
    const b2 = run("b2");
    expect([b2.executor.host, b2.environment_id]).toEqual(["dgx-h100-07", "env-dgx"]);
    expect(hostOf(b2, HOSTS)).toBe("dgx");
    expect(hostOf(b2, undefined)).toBe("dgx-h100-07");
    expect(hostOf({ ...b2, environment_id: "env-elsewhere" }, HOSTS)).toBe("dgx-h100-07");
  });

  test("sweepHref encodes both parts", () => {
    expect(sweepHref("rxn", "s-7f3a")).toBe("/s/rxn/s-7f3a");
    expect(sweepHref("a b", "s/1")).toBe("/s/a%20b/s%2F1");
  });
});
