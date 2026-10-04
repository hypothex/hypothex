import { describe, expect, test } from "bun:test";
import type { SweepParam, SweepSpec } from "../../src/api/models";
import {
  SORT_MEAN,
  SORT_N,
  type SweepCellRow,
  defaultSort,
  etaSeconds,
  fmtGpuHours,
  gpuHours,
  gpuHoursByHost,
  nextSeeds,
  nextSort,
  orderRuns,
  parseCell,
  parseCells,
  parseSeedCount,
  progressLabel,
  progressSegments,
  runUsd,
  sortCells,
  sweepCli,
  sweepStats,
} from "../../src/pages/components/SweepModel";
import { CELL_D, HOSTS, NOW, RUNS, makeSummary, rid, run } from "./sweepFixtures";

const SPEC: SweepSpec = makeSummary().spec;
const COUNTS = makeSummary().counts;
const ORDERED = orderRuns(RUNS, makeSummary().run_ids);
const param = (
  name: string,
  values: string[] | null,
  low: number | null = null,
  high: number | null = null,
  log = false,
): SweepParam => ({ name, values, low, high, log });

describe("sweepCli", () => {
  test("rebuilds the hx sweep command of a grid sweep", () => {
    expect(sweepCli(SPEC, RUNS)).toBe(
      "hx sweep -t fwd --grid lr=1e-4,3e-4 --grid beam=5,10 --seeds 1,2 --gpus 2 --queue " +
        "-H 'tune lr and beam' -- python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'",
    );
  });

  test("random samples, a host, and no runs yet", () => {
    const spec: SweepSpec = {
      ...SPEC,
      task: null,
      host: "gpu1",
      random: 8,
      seeds: [1, 2, 3],
      grid: [param("lr", null, 0.00001, 0.01, true), param("beam", ["5", "10"])],
      command_template: ["python", "train.py", "--lr", "{lr}", "--note", "a b"],
    };
    expect(sweepCli(spec, [])).toBe(
      "hx sweep --grid beam=5,10 --random 8 --param lr=0.00001:0.01:log --seeds 1,2,3 --host gpu1 " +
        "-- python train.py --lr '{lr}' --note 'a b'",
    );
  });

  test("quotes param values a shell would split", () => {
    const spec: SweepSpec = { ...SPEC, grid: [param("tag", ["a b", "c"])], seeds: [1], command_template: ["run"] };
    expect(sweepCli(spec, [])).toBe("hx sweep -t fwd --grid 'tag=a b,c' --seeds 1 -- run");
  });

  test("one seed other than 1 is a one-element list; braces are quoted, so bash cannot expand them", () => {
    const one: SweepSpec = {
      ...SPEC,
      grid: [param("x", ["1"])],
      seeds: [5],
      command_template: ["run", "--x={1,2}", "{seed}"],
    };
    // `--seeds 5` would be a count (seeds 1 to 5); `5,` is the list with seed 5
    expect(sweepCli(one, [])).toBe("hx sweep -t fwd --grid x=1 --seeds 5, -- run '--x={1,2}' '{seed}'");
    expect(sweepCli({ ...one, seeds: [1] }, [])).toContain(" --seeds 1 -- ");
    expect(sweepCli({ ...one, seeds: [3, 1] }, [])).toContain(" --seeds 3,1 -- ");
  });
});

describe("seeds to add", () => {
  test("nextSeeds continues after the largest seed; parseSeedCount accepts 1..20", () => {
    expect(nextSeeds([1, 2], 2)).toEqual([3, 4]);
    expect(nextSeeds([5, 1], 1)).toEqual([6]);
    expect(nextSeeds([], 3)).toEqual([1, 2, 3]);
    expect(["3", " 4 ", "0", "21", "2.5", "", "x"].map((t) => parseSeedCount(t))).toEqual([
      3,
      4,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

describe("ETA, GPU-hours and cost", () => {
  test("etaSeconds: median run time × work left ÷ runs running", () => {
    // finished runs took 1 h; b2 has run 30 min (30 min left); a2 waits (1 h)
    expect(etaSeconds(RUNS, NOW)).toBe(5400);
    const early = { ...run("b2"), run_id: rid("x9"), started_at: "2026-10-03T11:00:00Z" };
    // two running: (30 min + 0 + 1 h) ÷ 2
    expect(etaSeconds([...RUNS, early], NOW)).toBe(2700);
  });

  test("etaSeconds is null without a finished run or with nothing left", () => {
    expect(etaSeconds(RUNS.filter((r) => r.status !== "finished"), NOW)).toBeNull();
    expect(etaSeconds(RUNS.filter((r) => r.status === "finished"), NOW)).toBeNull();
  });

  test("gpuHours uses the final cost, else wall time × GPUs", () => {
    expect(gpuHours(run("d1"), NOW)).toBe(2);
    expect(gpuHours(run("b2"), NOW)).toBe(1);
    expect(gpuHours(run("a2"), NOW)).toBe(0);
    expect(gpuHours({ ...run("d1"), cost: null }, NOW)).toBe(2);
    const byHost = gpuHoursByHost(ORDERED, NOW, HOSTS);
    expect([...byHost.keys()]).toEqual(["gpu1", "dgx"]);
    expect(byHost.get("gpu1")).toBeCloseTo(6.2, 10);
    expect(byHost.get("dgx")).toBeCloseTo(5, 10);
    expect([fmtGpuHours(11.2), fmtGpuHours(6.2), fmtGpuHours(0)]).toEqual(["11", "6.2", "0.0"]);
  });

  test("gpuHours: a live SLURM run whose node reported no GPU indices counts what it asked for", () => {
    const b2 = run("b2");
    const slurm = {
      ...b2,
      cost: null,
      gpus_requested: 4,
      executor: { ...b2.executor, gpus: [], slurm_job_id: "81234" },
    };
    // the backend bills it for gpus_requested (cost.billed_gpus): SLURM reserved that many
    expect(gpuHours(slurm, NOW)).toBeCloseTo(4 * gpuHours({ ...b2, cost: null, executor: { ...b2.executor, gpus: [0] } }, NOW), 10);
    // no SLURM job: no GPUs held, none counted
    expect(gpuHours({ ...slurm, executor: { ...slurm.executor, slurm_job_id: null } }, NOW)).toBe(0);
  });

  test("runUsd: final cost, else API spend so far, else nothing", () => {
    expect(runUsd(run("c2"))).toBe(0.42);
    expect(runUsd(run("a2"))).toBeNull();
    const usage = { tokens_in: 0, tokens_out: 0, usd: 0.31, seconds: 0, calls: 1 };
    expect(runUsd({ ...run("a2"), usage })).toBe(0.31);
  });
});

describe("progress", () => {
  test("one segment per run: finished, running, queued, failed or lost, killed, pending", () => {
    expect(progressSegments(COUNTS)).toEqual(["f", "f", "f", "f", "f", "r", "q", "x"]);
    const more = { ...COUNTS, killed: 1, lost: 1, total: 11 };
    expect(progressSegments(more)).toEqual(["f", "f", "f", "f", "f", "r", "q", "x", "x", "k", "n"]);
    expect(progressLabel(COUNTS)).toBe("5 finished, 1 running, 1 queued, 1 failed");
    expect(progressLabel(more)).toBe("5 finished, 1 running, 1 queued, 2 failed, 1 killed, 1 pending");
  });
});

function raw(id: string, lr: string, beam: string, warmup: string, n: number, mean: number | null): unknown {
  return {
    params: { lr, beam, warmup },
    group_id: n > 0 ? `g-${id}` : null,
    n,
    mean,
    lo: mean === null ? null : mean - 0.02,
    hi: mean === null ? null : mean + 0.02,
    std: null,
    run_ids: [`20261003-${id}`],
    runs: [{ run_id: `20261003-${id}`, status: mean === null ? "queued" : "finished", seed: 1 }],
  };
}

const TABLE = parseCells([
  raw("t1", "1e-4", "5", "100", 2, 0.8),
  raw("t2", "3e-4", "5", "100", 2, 0.85),
  raw("t3", "1e-3", "10", "0", 0, null),
  raw("t4", "3e-5", "10", "0", 1, 0.82),
]);
const lrs = (cs: SweepCellRow[]): (string | undefined)[] => cs.map((c) => c.params.lr);

describe("table sort", () => {
  test("by mean (best first, unscored last), by a numeric param, by n", () => {
    expect(lrs(sortCells(TABLE, defaultSort(true)))).toEqual(["3e-4", "3e-5", "1e-4", "1e-3"]);
    expect(lrs(sortCells(TABLE, defaultSort(false)))).toEqual(["1e-4", "3e-5", "3e-4", "1e-3"]);
    expect(lrs(sortCells(TABLE, { key: "lr", dir: "asc" }))).toEqual(["3e-5", "1e-4", "3e-4", "1e-3"]);
    expect(lrs(sortCells(TABLE, { key: "lr", dir: "desc" }))).toEqual(["1e-3", "3e-4", "1e-4", "3e-5"]);
    expect(lrs(sortCells(TABLE, { key: SORT_N, dir: "asc" }))).toEqual(["1e-3", "3e-5", "1e-4", "3e-4"]);
    expect(lrs(sortCells(TABLE, { key: "warmup", dir: "asc" }))).toEqual(["1e-3", "3e-5", "1e-4", "3e-4"]);
  });

  test("nextSort flips the active column and starts others ascending", () => {
    expect(defaultSort(true)).toEqual({ key: SORT_MEAN, dir: "desc" });
    expect(nextSort(defaultSort(true), SORT_MEAN, true)).toEqual({ key: SORT_MEAN, dir: "asc" });
    expect(nextSort(defaultSort(true), "lr", true)).toEqual({ key: "lr", dir: "asc" });
    expect(nextSort({ key: "lr", dir: "asc" }, "lr", true)).toEqual({ key: "lr", dir: "desc" });
    expect(nextSort({ key: "lr", dir: "asc" }, SORT_MEAN, false)).toEqual({ key: SORT_MEAN, dir: "asc" });
  });

  // a sweep may name a param `n` or `mean`: those must not hit the built-in columns
  const named = (n: string, mean: string, scored: number, score: number): unknown => ({
    params: { n, mean },
    group_id: `g-${n}-${mean}`,
    n: scored,
    mean: score,
    lo: null,
    hi: null,
    std: null,
    run_ids: [],
    runs: [],
  });
  const NAMED = parseCells([named("3", "b", 1, 0.5), named("1", "c", 3, 0.9), named("2", "a", 2, 0.7)]);
  const ns = (key: string): (string | undefined)[] => sortCells(NAMED, { key, dir: "asc" }).map((c) => c.params.n);

  test("params named n and mean sort by the param, the built-in keys by count and score", () => {
    expect(ns("n")).toEqual(["1", "2", "3"]);
    expect(ns("mean")).toEqual(["2", "3", "1"]);
    expect(ns(SORT_N)).toEqual(["3", "2", "1"]);
    expect(ns(SORT_MEAN)).toEqual(["3", "2", "1"]);
  });

  test("a param named mean starts ascending; the metric starts best first", () => {
    const prev = { key: SORT_N, dir: "asc" as const };
    expect(nextSort(prev, "mean", true)).toEqual({ key: "mean", dir: "asc" });
    expect(nextSort(prev, SORT_MEAN, true)).toEqual({ key: SORT_MEAN, dir: "desc" });
    expect(nextSort(prev, "n", true)).toEqual({ key: "n", dir: "asc" });
  });
});

describe("sweepStats", () => {
  test("best, interval, counts, cost with GPU-hours, ETA", () => {
    const items = sweepStats({
      counts: COUNTS,
      totalUsd: 12.5,
      best: parseCell(CELL_D),
      names: ["lr", "beam"],
      metric: "top1",
      unit: "",
      runs: ORDERED,
      hosts: HOSTS,
      now: NOW,
    });
    expect(items).toEqual([
      { label: "best top1", value: "0.9120", tooltip: "Mean top1 of lr 3e-4, beam 10 over 2 seeds" },
      {
        label: "95% CI",
        value: "0.908–0.916",
        tooltip: "Best cell: test-set 95% interval, or over seeds without per-example scores",
      },
      { label: "finished", value: "5", unit: "/ 8", tooltip: "Runs finished" },
      { label: "running", value: "1", tooltip: "Runs running now" },
      { label: "queued", value: "1", tooltip: "Runs waiting in a host queue" },
      { label: "failed", value: "1", tooltip: "c2 failed, exit 1" },
      { label: "cost, 11 GPU-h", value: "$12.50", tooltip: "gpu1 6.2 GPU-h\ndgx 5.0 GPU-h" },
      { label: "ETA", value: "1h 30m", tooltip: "Median finished run time × runs left ÷ runs running" },
    ]);
  });

  test("an empty sweep shows dashes", () => {
    const counts = { queued: 0, running: 0, finished: 0, failed: 0, killed: 0, lost: 0, total: 0 };
    const items = sweepStats({
      counts,
      totalUsd: 0,
      best: null,
      names: ["lr"],
      metric: "score",
      unit: "",
      runs: [],
      hosts: undefined,
      now: NOW,
    });
    expect(items.map((i) => [i.label, i.value])).toEqual([
      ["best score", "—"],
      ["95% CI", "—"],
      ["finished", "0"],
      ["running", "0"],
      ["queued", "0"],
      ["failed", "0"],
      ["cost, 0.0 GPU-h", "$0"],
      ["ETA", "—"],
    ]);
    expect(items[0]?.tooltip).toBe("No scored runs yet");
    expect(items[6]?.tooltip).toBe("No GPU time yet");
  });
});
