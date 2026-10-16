/** The texts of the run sidebar (spec 4.3): status with exit or reason, host, GPUs, commit, config. */
import type { HostRow, RunRecord } from "../api/models";
import { STATUS_WORD } from "../chrome/StatusIcon";
import { type PlaceRow, placementRows } from "../pages/components/Placement";
import { fmtWait, hostLabel, type RunPhase, secondsSince } from "../pages/components/remote";
import type { GitState } from "../pages/components/WhereList";

function capitalized(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

/** "Finished · exit 0", "Failed · exit 1 · OOM", "Lost · <reason>", "Stale · dgx unreachable 5m". */
export function statusText(record: RunRecord, phase: RunPhase, host: HostRow | null, now: number, reason: string | null): string {
  if (phase === "stale") {
    const gone = host ? secondsSince(host.state.since, now) : null;
    const name = hostLabel(record, host);
    return gone === null ? `Stale · ${name} unreachable` : `Stale · ${name} unreachable ${fmtWait(gone)}`;
  }
  const why = record.end_reason?.trim() || "";
  if (record.status === "lost") {
    const told = why || reason?.trim() || "";
    return `Lost · ${told || (record.exit_code === null ? "no exit code" : `exit ${record.exit_code}`)}`;
  }
  const word = capitalized(STATUS_WORD[record.status] ?? record.status);
  return [word, record.exit_code !== null ? `exit ${record.exit_code}` : "", why].filter(Boolean).join(" · ");
}

/** A hub run's machine (with its GPUs); a remote run's host name and kind. */
export function hostText(record: RunRecord, phase: RunPhase, host: HostRow | null): string {
  if (phase === "local") {
    const gpus = record.executor.gpus ?? [];
    return gpus.length > 0 ? `${record.host} · GPU ${gpus.join(", ")}` : record.host;
  }
  const kind = host?.kind ?? (record.executor.slurm_job_id ? "slurm" : "ssh");
  return `${hostLabel(record, host)} · ${kind}`;
}

/** Mean utilisation and total memory of the GPUs a running remote run holds; null when unknown. */
export function gpuUse(record: RunRecord, phase: RunPhase, host: HostRow | null): string | null {
  const gpus = record.executor.gpus ?? [];
  // a SLURM job's GPU indices are on its compute node, not the login node's GPUs
  if (phase !== "running" || !host || gpus.length === 0 || record.executor.slurm_job_id) return null;
  const held = host.gpus.filter((g) => gpus.includes(g.index));
  if (held.length === 0) return null;
  const util = held.reduce((a, g) => a + g.util, 0) / held.length;
  const mem = held.reduce((a, g) => a + g.mem_used_mb, 0) / 1024;
  return `${Math.round(util)}% · ${Math.round(mem)} GB`;
}

/** Short commit, marked " · dirty" or " · untracked"; null without a commit. */
export function commitText(git: GitState): string | null {
  if (!git.commit) return null;
  const state = git.dirty ? " · dirty" : (git.untracked_count ?? 0) > 0 ? " · untracked" : "";
  return `${git.commit.slice(0, 7)}${state}`;
}

export interface ConfigRow {
  key: string;
  value: string;
  varies: boolean;
}

/** The run's params in their order, then its seed; `varies` tints values that differ in the task. */
export function configRows(record: RunRecord, varying: readonly string[], seedVaries: boolean): ConfigRow[] {
  const rows = Object.entries(record.params).map(([key, value]) => ({ key, value, varies: varying.includes(key) }));
  if (record.seed !== null) rows.push({ key: "seed", value: String(record.seed), varies: seedVaries });
  return rows;
}

/** Placement rows (Job, Node, GPUs, PID, Queue) of a remote run; Host and Cost have their own rows. */
export function placementExtras(record: RunRecord, phase: RunPhase, host: HostRow | null): PlaceRow[] {
  return placementRows(record, phase, host).filter((row) => row.key !== "Host" && row.key !== "Cost");
}
