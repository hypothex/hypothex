/**
 * Sweep page fixtures: lr {1e-4, 3e-4} × beam {5, 10} × seeds {1, 2} = 8 runs on gpu1
 * and dgx. dgx is stale. Status: 5 finished, b2 running (on dgx, so drawn stale),
 * a2 queued at position 2, c2 failed with exit 1. "Now" is 2026-10-03 12:00 UTC.
 *
 * As the backend writes them, `executor.host` and `host` hold each machine's own hostname
 * (`sv-a100-01`, `dgx-h100-07`), not the hub's host names; runs match their host by
 * `environment_id` (`env-gpu1`, `env-dgx`).
 */
import type { HostRow, Leaderboard, LeaderboardRow, RunRecord, RunStatus, SweepSummary } from "../../src/api/models";
import { makeBoard, makeRecord } from "./fixtures";

export const PROJECT = "rxn";
export const TASK = "fwd";
export const SWEEP_ID = "s-7f3a";
/** The member tag the backend sends as `SweepSummary.tag` (the hub's id prefix, then the id). */
export const SWEEP_TAG = `sweep:0a1b2c3d:${SWEEP_ID}`;
export const NOW = Date.parse("2026-10-03T12:00:00Z");
export const TEMPLATE = ["python", "train.py", "--lr", "{lr}", "--beam", "{beam}", "--seed", "{seed}"];

/** Full run id for a short tail: `rid("a1")` → `20261003-091200-fwd-a1` (`shortId` gives `a1`). */
export const rid = (tail: string): string => `20261003-091200-fwd-${tail}`;

interface RunSpec {
  tail: string;
  lr: string;
  beam: string;
  seed: number;
  status: RunStatus;
  host: string;
  started?: string;
  ended?: string;
  gpuHours?: number;
  usd?: number;
  queuePos?: number;
  exit?: number;
}

const DONE = { started: "2026-10-03T09:00:00Z", ended: "2026-10-03T10:00:00Z", gpuHours: 2, usd: 2.4 };

/** Each fake host's own hostname (`socket.gethostname()`), what the backend puts in `executor.host`. */
export const HOSTNAME: Record<string, string> = { gpu1: "sv-a100-01", dgx: "dgx-h100-07" };

const RUN_SPECS: RunSpec[] = [
  { tail: "a1", lr: "1e-4", beam: "5", seed: 1, status: "finished", host: "gpu1", ...DONE },
  { tail: "b1", lr: "1e-4", beam: "10", seed: 1, status: "finished", host: "gpu1", ...DONE },
  { tail: "c1", lr: "3e-4", beam: "5", seed: 1, status: "finished", host: "gpu1", ...DONE },
  { tail: "d1", lr: "3e-4", beam: "10", seed: 1, status: "finished", host: "dgx", ...DONE },
  { tail: "a2", lr: "1e-4", beam: "5", seed: 2, status: "queued", host: "gpu1", queuePos: 2 },
  { tail: "b2", lr: "1e-4", beam: "10", seed: 2, status: "running", host: "dgx", started: "2026-10-03T11:30:00Z" },
  {
    tail: "c2",
    lr: "3e-4",
    beam: "5",
    seed: 2,
    status: "failed",
    host: "gpu1",
    started: "2026-10-03T10:00:00Z",
    ended: "2026-10-03T10:06:00Z",
    gpuHours: 0.2,
    usd: 0.42,
    exit: 1,
  },
  { tail: "d2", lr: "3e-4", beam: "10", seed: 2, status: "finished", host: "dgx", ...DONE },
];

/** One sweep run; spreads `makeRecord` first so every other required field is present. */
function sweepRun(s: RunSpec): RunRecord {
  const base = makeRecord({ run_id: rid(s.tail) });
  const ran = s.started !== undefined;
  return {
    ...base,
    project: PROJECT,
    task: TASK,
    environment_id: `env-${s.host}`,
    host: HOSTNAME[s.host] ?? s.host,
    hypothesis: "tune lr and beam",
    command: ["python", "train.py", "--lr", s.lr, "--beam", s.beam, "--seed", String(s.seed)],
    command_template: TEMPLATE,
    params: { lr: s.lr, beam: s.beam },
    vars: { lr: s.lr, beam: s.beam },
    seed: s.seed,
    status: s.status,
    created_at: "2026-10-03T09:00:00Z",
    started_at: s.started ?? null,
    ended_at: s.ended ?? null,
    exit_code: s.exit ?? (s.status === "finished" ? 0 : null),
    artifacts: [],
    tags: [SWEEP_TAG],
    created_by: "agent:tuner",
    executor: {
      ...base.executor,
      host: HOSTNAME[s.host] ?? s.host,
      gpus: ran ? [0, 1] : [],
      slurm_job_id: null,
      node: null,
      queue_position: s.queuePos ?? null,
    },
    cost:
      s.gpuHours !== undefined
        ? { gpu_hours: s.gpuHours, gpu_usd: s.usd ?? 0, api_usd: 0, total_usd: s.usd ?? 0 }
        : null,
    sweep_id: SWEEP_ID,
    gpus_requested: 2,
  };
}

/** The 8 runs in launch (`SweepSummary.run_ids`) order. */
export const RUNS: RunRecord[] = RUN_SPECS.map(sweepRun);

export function run(tail: string): RunRecord {
  return RUNS.find((r) => r.run_id === rid(tail)) as RunRecord;
}

type RawRun = [tail: string, status: RunStatus, seed: number];

function rawCell(
  lr: string,
  beam: string,
  n: number,
  mean: number | null,
  lo: number | null,
  hi: number | null,
  std: number | null,
  runs: RawRun[],
): Record<string, unknown> {
  return {
    params: { lr, beam },
    group_id: n > 0 ? `g-${lr}-${beam}` : null,
    n,
    mean,
    lo,
    hi,
    std,
    run_ids: runs.map(([tail]) => rid(tail)),
    runs: runs.map(([tail, status, seed]) => ({ run_id: rid(tail), status, seed })),
  };
}

/** `summarize_sweep` cells as JSON (contract 1.7 plus the backend plan's optional `std` and `runs`). */
export const CELL_A = rawCell("1e-4", "5", 1, 0.89, 0.885, 0.895, null, [
  ["a1", "finished", 1],
  ["a2", "queued", 2],
]);
export const CELL_B = rawCell("1e-4", "10", 1, 0.9, 0.895, 0.905, null, [
  ["b1", "finished", 1],
  ["b2", "running", 2],
]);
export const CELL_C = rawCell("3e-4", "5", 1, 0.904, 0.899, 0.909, null, [
  ["c1", "finished", 1],
  ["c2", "failed", 2],
]);
export const CELL_D = rawCell("3e-4", "10", 2, 0.912, 0.908, 0.916, 0.0014, [
  ["d1", "finished", 1],
  ["d2", "finished", 2],
]);
export const RAW_CELLS: Record<string, unknown>[] = [CELL_A, CELL_B, CELL_C, CELL_D];

/** `GET /api/v1/sweeps/rxn/s-7f3a`; `over` replaces summary fields, `specOver` spec fields. */
export function makeSummary(
  over: Record<string, unknown> = {},
  specOver: Record<string, unknown> = {},
): SweepSummary {
  return {
    spec: {
      id: SWEEP_ID,
      project: PROJECT,
      task: TASK,
      host: null,
      grid: [
        { name: "lr", values: ["1e-4", "3e-4"], low: null, high: null, log: false },
        { name: "beam", values: ["5", "10"], low: null, high: null, log: false },
      ],
      random: null,
      seeds: [1, 2],
      command_template: TEMPLATE,
      created_by: "agent:tuner",
      created_at: "2026-10-03T09:12:00Z",
      ...specOver,
    },
    // membership is derived by the backend from the runs tagged `tag` (ruling S8)
    run_ids: ["a1", "b1", "c1", "d1", "a2", "b2", "c2", "d2"].map(rid),
    tag: SWEEP_TAG,
    counts: { queued: 1, running: 1, finished: 5, failed: 1, killed: 0, lost: 0, total: 8 },
    cells: RAW_CELLS,
    best: CELL_D,
    headline: "lr 3e-4, beam 10: 0.912 top1, +0.008 over beam 5",
    total_usd: 12.5,
    ...over,
  } as unknown as SweepSummary;
}

function boardRow(group: string, ids: string[], values: number[], mean: number): LeaderboardRow {
  const base = makeBoard().rows[1] as LeaderboardRow;
  return {
    ...base,
    group_id: group,
    run_ids: ids,
    latest_run_id: ids.at(-1) ?? "",
    n: values.length,
    primary: { mean, std: 0, n: values.length, ci_low: null, ci_high: null },
    seed_values: { "top1/value": values },
    identical_seeds: false,
    test_interval: null,
    vs_best: null,
  };
}

/** The task leaderboard: one row per scored cell, keyed by the cells' group ids. */
export function makeSweepBoard(): Leaderboard {
  return {
    ...makeBoard(),
    project: PROJECT,
    task: TASK,
    primary: "top1/value",
    higher_is_better: true,
    metric_versions: { top1: "v1" },
    unit: "",
    rows: [
      boardRow("g-3e-4-10", [rid("d1"), rid("d2")], [0.911, 0.913], 0.912),
      boardRow("g-3e-4-5", [rid("c1")], [0.904], 0.904),
      boardRow("g-1e-4-10", [rid("b1")], [0.9], 0.9),
      boardRow("g-1e-4-5", [rid("a1")], [0.89], 0.89),
    ],
    headline: "top1 0.912",
    stat_strip: [],
  };
}

function hostRow(name: string, state: string, since: string): HostRow {
  return {
    name,
    kind: "ssh",
    state: {
      name,
      kind: "ssh",
      state,
      since,
      message: "",
      environment_id: `env-${name}`,
      hx_version: "0.2.0",
      last_sequence: 0,
      local_port: null,
    },
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 0,
    projects: [PROJECT],
  } as unknown as HostRow;
}

/** `GET /api/v1/hosts`: gpu1 connected, dgx stale since 11:56 (4 minutes before NOW). */
export const HOSTS: HostRow[] = [
  hostRow("gpu1", "connected", "2026-10-03T08:00:00Z"),
  hostRow("dgx", "stale", "2026-10-03T11:56:00Z"),
];

/** `staleHosts(HOSTS)`: environment id → since, for every host that is not connected. */
export const STALE: ReadonlyMap<string, string> = new Map([["env-dgx", "2026-10-03T11:56:00Z"]]);
