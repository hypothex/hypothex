/**
 * Remote run state for the run page (spec 5.6, 8A.5, 8A.8): the phase a run is shown in,
 * the hosts row that serves it, and the short texts each phase needs. Pure functions; the
 * page does the fetching. A run is remote when its detail has a `host_state`; its host is
 * found by `environment_id`, never by `executor.host` (the backend writes the machine's own
 * hostname there, on every run).
 */
import { fmtClock, fmtTime, fmtUsd, parseTime } from "./format";
import { gpuCountLabel, hostRowForRun } from "./HostsPanel";
import { sweepHref } from "./SweepModel";
import type { CostTotals, GpuInfo, HostRow, RunDetail, RunRecord } from "./types";

/**
 * How the run page shows a run.
 *
 * `local`: a hub run (the phase 1b layout). `queued`: waiting in an SSH host's hx queue.
 * `pending`: submitted to SLURM, not started. `running`: running on a host that answers.
 * `stale`: queued or running on a host the hub cannot reach now (derived, never stored).
 * `lost`: the env server gave the run up. `ended`: a finished, failed or killed remote run.
 */
export type RunPhase = "local" | "queued" | "pending" | "running" | "stale" | "lost" | "ended";

/**
 * The phase of a run. `host_state` null (or missing, on a phase 1 server) is a hub run: the
 * backend sets it only for runs of a host's environment. `executor.host` says nothing here,
 * since the backend fills it on every run, hub runs too.
 */
export function runPhase(detail: RunDetail): RunPhase {
  const record = detail.record;
  if (record.status === "lost") return "lost";
  const conn = detail.host_state ?? null;
  if (conn === null) return "local";
  const active = record.status === "queued" || record.status === "running";
  if (active && conn !== "connected") return "stale";
  if (record.status === "queued") return record.executor.slurm_job_id ? "pending" : "queued";
  if (record.status === "running") return "running";
  return "ended";
}

/**
 * The `GET /api/v1/hosts` row of a remote run's host (`hostRowForRun`: matched by
 * `environment_id`); null for a hub run, or while the hosts list is not loaded or failed.
 */
export function runHostRow(detail: RunDetail, hosts: readonly HostRow[] | undefined): HostRow | null {
  if ((detail.host_state ?? null) === null) return null;
  return hostRowForRun(detail.record, hosts);
}

/**
 * How texts name a remote run's host: the hub's name for it (`host.name`), else, without the
 * hosts list, the machine's own hostname (`record.host`). Only for display: Reconnect needs
 * `host.name`.
 */
export function hostLabel(record: RunRecord, host: HostRow | null): string {
  return host?.name ?? record.host;
}

const SUFFIX: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };

/** `1st`, `2nd`, `3rd`, `4th`, `11th`, `21st`. */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${SUFFIX[n % 10] ?? "th"}`;
}

/** A waiting time, `45s`, `12m`, `1h 52m`: the sweep page's age format. */
export { fmtAge as fmtWait } from "./SweepModel";

/** Seconds from `iso` to `now` (0 for a future time); null for an unreadable time. */
export function secondsSince(iso: string, now: number): number | null {
  const t = parseTime(iso);
  return Number.isNaN(t) ? null : Math.max(0, (now - t) / 1000);
}

/** `CUDA_VISIBLE_DEVICES=0,1`. */
export function visibleDevices(gpus: readonly number[]): string {
  return `CUDA_VISIBLE_DEVICES=${gpus.join(",")}`;
}

/** The hosts grid's GPU model name: `NVIDIA A100 80GB PCIe` → `A100`. */
export { shortGpuName } from "./HostsPanel";

/**
 * `2×A100 80GB` when the GPUs (the given indices, else all of the host's) share one model
 * and size; `2 GPUs` when they differ or are unknown. Same text as the hosts grid
 * (`gpuCountLabel`).
 */
export function gpuLabel(count: number, host: HostRow | null, indices: readonly number[] = []): string {
  const pool: GpuInfo[] = host?.gpus ?? [];
  const picked = indices.length > 0 ? pool.filter((g) => indices.includes(g.index)) : pool;
  return gpuCountLabel(count, picked);
}

/** GPUs no hx run holds and no outside process uses (spec 8A.5). */
export function freeGpus(host: HostRow): number {
  return host.gpus.filter((g) => g.run_id === null && !g.external).length;
}

export interface LostReason {
  title: string;
  tooltip: string;
  parts: string[];
}

/** Where the cause of a lost run is when this tab has not seen it: in its `run.lost` event. */
const LOST_TIP = "The env server marked this run lost. Its run.lost event has the reason.";
/** The tooltip when the reason shown came from that event. */
const REASON_TIP = "Reason from the run's run.lost event.";

/**
 * What a lost run's record says: the SLURM job, the node, when, and the exit code. The env
 * server's own reason (`SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit
 * record`) is in the `run.lost` event, not in the run detail: pass it as `reason` when the
 * tab saw that event (`useLostReason`), and it comes first. Without it the words stay
 * neutral: a job lost to `NODE_FAIL` is still in `sacct`, and a dead supervisor is only one
 * of the causes, so neither is guessed here.
 */
export function lostReason(record: RunRecord, reason: string | null = null): LostReason {
  const ex = record.executor;
  const parts: string[] = [];
  if (ex.node) parts.push(ex.node);
  if (record.ended_at) parts.push(fmtTime(record.ended_at));
  parts.push(record.exit_code === null ? "no exit code" : `exit ${record.exit_code}`);
  const title = ex.slurm_job_id ? `SLURM job ${ex.slurm_job_id} lost` : "run lost";
  const why = reason?.trim() ?? "";
  return why === "" ? { title, tooltip: LOST_TIP, parts } : { title, tooltip: REASON_TIP, parts: [why, ...parts] };
}

/**
 * The page title for a queued, pending, stale or lost run (`<label>: queued 2nd on gpu1`);
 * null when the run keeps its hypothesis as the title.
 */
export function stateTitle(label: string, phase: RunPhase, record: RunRecord, host: HostRow | null): string | null {
  const name = hostLabel(record, host);
  switch (phase) {
    case "queued": {
      const pos = record.executor.queue_position ?? null;
      return pos === null ? `${label}: queued on ${name}` : `${label}: queued ${ordinal(pos)} on ${name}`;
    }
    case "pending":
      return `${label}: pending on ${name}`;
    case "stale":
      return host ? `${label}: stale since ${fmtClock(host.state.since)}` : `${label}: ${name} unreachable`;
    case "lost":
      return record.ended_at ? `${label}: lost at ${fmtClock(record.ended_at)}` : `${label}: lost`;
    default:
      return null;
  }
}

/** The sweep page of a run's sweep (contract 4, route `/s/:project/:id`). */
export { sweepHref } from "./SweepModel";

/** `3.50 GPU h, API $0.42`: what a cost is made of. */
export function costNote(cost: CostTotals): string {
  return `${cost.gpu_hours.toFixed(2)} GPU h, API ${fmtUsd(cost.api_usd)}`;
}

/** A cost as the run page shows it: the total (or `—`) and what it is made of. */
export interface CostShown {
  value: string;
  note: string;
  /** GPU hours on a host with no GPU rate: the total is unknown. */
  unpriced: boolean;
}

/**
 * How the run page shows a run's cost (spec 8A.7), in the stat strip and the Placement
 * panel alike. No cost, or an all-zero one (a hub or CPU run), is nothing to show. GPU
 * hours left unpriced because the host row says it has no rate (`null`) make the total
 * unknown (`—`); zero GPU dollars alone prove nothing (free GPUs, a tiny charge rounded).
 * `host` is the run's hosts row, or null without the hosts list.
 */
export function costShown(cost: CostTotals | null | undefined, host: HostRow | null): CostShown | null {
  if (!cost || (cost.total_usd <= 0 && cost.gpu_hours <= 0)) return null;
  const unpriced = host?.usd_per_gpu_hour === null && cost.gpu_hours > 0 && cost.gpu_usd === 0;
  return unpriced
    ? { value: "—", note: `${costNote(cost)}, no GPU rate for this host`, unpriced }
    : { value: fmtUsd(cost.total_usd), note: costNote(cost), unpriced };
}

/** Characters of the hub's environment id a sweep tag names (the backend's `SWEEP_OWNER_CHARS`). */
export const SWEEP_OWNER_CHARS = 8;
const OWNED_SWEEP_TAG = /^sweep:([^:]+):(.+)$/;

/** The run page's sweep crumb. */
export interface SweepCrumb {
  id: string;
  /** `/s/<project>/<id>` when this hub owns the sweep; null: plain text. */
  href: string | null;
  /** Why there is no link (the tooltip); null with a link or while the hub's id is unknown. */
  why: string | null;
}

/**
 * The crumb for a run's sweep. Sweep ids are per hub, and one host can serve two hubs, so
 * the link is made only when the run's owner-qualified tag `sweep:<owner8>:<sweep_id>`
 * names this hub (`owner8`: the first 8 characters of its environment id). A run of another
 * hub's sweep, or one without that tag, shows the id as plain text: this hub has no such
 * sweep page, or a different sweep under the same id.
 */
export function sweepCrumb(
  record: Pick<RunRecord, "project" | "sweep_id" | "tags">,
  hubEnvironmentId: string | null,
): SweepCrumb | null {
  const id = record.sweep_id;
  if (!id) return null;
  if (hubEnvironmentId === null) return { id, href: null, why: null };
  let owner: string | null = null;
  for (const tag of record.tags) {
    const m = OWNED_SWEEP_TAG.exec(tag);
    if (m && m[2] === id) {
      owner = m[1] ?? null;
      break;
    }
  }
  if (owner === null) return { id, href: null, why: "no sweep tag on this run" };
  if (owner !== hubEnvironmentId.slice(0, SWEEP_OWNER_CHARS)) {
    return { id, href: null, why: `sweep of another hub (${owner})` };
  }
  return { id, href: sweepHref(record.project, id), why: null };
}
