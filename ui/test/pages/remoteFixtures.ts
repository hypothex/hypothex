/**
 * Remote run records for the run page tests, matching the phase 2 mockups.
 *
 * Hosts come from `../api/phase2-fixtures` (the hub's `local` row, gpu1 ssh with 3 GPUs and
 * queue 3, mccleary slurm, dgx stale since 14:28:02). Every test runs its clock at `NOW`.
 * As the backend writes them, `host` and `executor.host` are each machine's own hostname
 * (`sv-a100-01`, `dgx-h100-07`, `mccleary-login1`), not the hub's host names; the run page
 * finds the host by `environment_id` (`env-gpu1`, `env-dgx`, `env-mccleary`).
 */
import type { ConnState, ExecutorInfo, HostRow, RunDetail, RunRecord } from "../../src/pages/components/types";
import { COST, HOSTS, REMOTE_EXECUTOR } from "../api/phase2-fixtures";
import { makeDetail, makeRecord } from "./fixtures";

/** 2026-10-03 14:34:00 UTC. */
export const NOW = Date.parse("2026-10-03T14:34:00Z");

function host(name: string): HostRow {
  const row = HOSTS.find((h) => h.name === name);
  if (!row) throw new Error(`no fixture host ${name}`);
  return row;
}

export const GPU1 = host("gpu1");
export const MCCLEARY = host("mccleary");
export const DGX = host("dgx");

export const QUEUED_ID = "20261003-142104-toy-test-f2c8";
export const RUNNING_ID = "20261003-124150-toy-test-c90b";
export const STALE_ID = "20261003-110355-toy-test-a9d3";
export const LOST_ID = "20261003-012210-toy-test-5e9a";
export const PENDING_ID = "20261003-143000-toy-test-77aa";

const NO_EXECUTOR: ExecutorInfo = {
  type: "local",
  pid: null,
  pid_create_time: null,
  child_pid: null,
  host: null,
  gpus: [],
  slurm_job_id: null,
  node: null,
  queue_position: null,
};

const REMOTE_BASE: Partial<RunRecord> = {
  task: null,
  started_at: null,
  ended_at: null,
  exit_code: null,
  artifacts: [],
  tags: [],
  cost: null,
  sweep_id: null,
  gpus_requested: 0,
};

/** gpu1's machine: what the backend writes into `host` and `executor.host` of its runs. */
const ON_GPU1: Partial<RunRecord> = { environment_id: "env-gpu1", host: "sv-a100-01" };
const ON_DGX: Partial<RunRecord> = { environment_id: "env-dgx", host: "dgx-h100-07" };
const ON_MCCLEARY: Partial<RunRecord> = { environment_id: "env-mccleary", host: "mccleary-login1" };

/** Queued 2nd of 3 on gpu1, needs 2 GPUs, waiting since 14:21:04. */
export function queuedRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_GPU1,
    run_id: QUEUED_ID,
    hypothesis: "lr 1e-3 with beam 1",
    status: "queued",
    created_at: "2026-10-03T14:21:04Z",
    created_by: "agent:tuner",
    gpus_requested: 2,
    executor: { ...NO_EXECUTOR, host: "sv-a100-01", queue_position: 2 },
    ...over,
  });
}

/** Running on gpu1 GPU 0 since 12:42:00, child pid 2291045. */
export function runningRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_GPU1,
    run_id: RUNNING_ID,
    hypothesis: "aug long run seed 1",
    status: "running",
    created_at: "2026-10-03T12:41:50Z",
    started_at: "2026-10-03T12:42:00Z",
    gpus_requested: 1,
    executor: { ...NO_EXECUTOR, pid: 2291040, child_pid: 2291045, host: "sv-a100-01", gpus: [0] },
    ...over,
  });
}

/** Running on dgx GPUs 4 and 5 since 11:04:00; dgx is stale. */
export function staleRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_DGX,
    run_id: STALE_ID,
    hypothesis: "lr 1e-3 with beam 10",
    status: "running",
    created_at: "2026-10-03T11:03:55Z",
    started_at: "2026-10-03T11:04:00Z",
    gpus_requested: 2,
    executor: { ...NO_EXECUTOR, pid: 118730, child_pid: 118734, host: "dgx-h100-07", gpus: [4, 5] },
    ...over,
  });
}

/** SLURM job 4471023 on mccleary, lost at 02:14:37, part of sweep s-7f3a, cost $2.17. */
export function lostRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_MCCLEARY,
    run_id: LOST_ID,
    hypothesis: "aug long run seed 2",
    status: "lost",
    created_at: "2026-10-03T01:22:10Z",
    started_at: "2026-10-03T01:22:10Z",
    ended_at: "2026-10-03T02:14:37Z",
    gpus_requested: 2,
    cost: COST,
    sweep_id: "s-7f3a",
    executor: { ...REMOTE_EXECUTOR },
    ...over,
  });
}

/** SLURM job 4471031 on mccleary, pending since 14:30:00, needs 2 GPUs. */
export function pendingRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    ...REMOTE_BASE,
    ...ON_MCCLEARY,
    run_id: PENDING_ID,
    hypothesis: "aug long run seed 3",
    status: "queued",
    created_at: "2026-10-03T14:30:00Z",
    gpus_requested: 2,
    executor: { ...NO_EXECUTOR, type: "slurm", host: "mccleary-login1", slurm_job_id: "4471031" },
    ...over,
  });
}

/** A run detail as the hub returns it, with the host's connection state. */
export function remoteDetail(record: RunRecord, hostState: ConnState | null = "connected"): RunDetail {
  return makeDetail(record, { host_state: hostState, scores: [] });
}
