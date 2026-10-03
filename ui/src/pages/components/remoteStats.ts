/**
 * Stat strip items for a remote run (spec 8A.5, 8A.7, mockups shot-run-*): queue place and
 * GPU need while it waits, GPU use while it runs, how long its host is gone when stale.
 */
import { runSeconds } from "./format";
import { fmtWait, freeGpus, hostLabel, type RunPhase, secondsSince } from "./remote";
import type { StatItem } from "./StatStrip";
import type { HostRow, RunRecord } from "./types";

/** `host` is the run's hosts row (`runHostRow`), or null without the hosts list. */
export function remoteStats(
  record: RunRecord,
  phase: RunPhase,
  host: HostRow | null,
  now: number = Date.now(),
): StatItem[] {
  const name = hostLabel(record, host);
  const ex = record.executor;
  const gpus = ex.gpus ?? [];
  const out: StatItem[] = [];
  if (phase === "queued" || phase === "pending") {
    const pos = ex.queue_position ?? null;
    if (phase === "queued" && pos !== null) {
      out.push({
        label: "position",
        value: String(pos),
        unit: host ? `/ ${host.queue}` : null,
        tooltip: `place in the ${name} queue`,
      });
    }
    out.push({
      label: "needs",
      value: String(record.gpus_requested ?? 0),
      unit: "GPU",
      tooltip: "GPUs this run needs on one host",
    });
    if (phase === "queued" && host && host.gpus.length > 0) {
      out.push({
        label: `free on ${name}`,
        value: String(freeGpus(host)),
        unit: `/ ${host.gpus.length}`,
        tooltip: `GPUs on ${name} no run or outside process uses`,
      });
    }
    if (phase === "pending" && ex.slurm_job_id) {
      out.push({ label: "job", value: ex.slurm_job_id, tooltip: "SLURM job id" });
    }
    const waited = secondsSince(record.created_at, now);
    if (waited !== null) {
      out.push({ label: "waiting", value: fmtWait(waited), tooltip: `queued at ${record.created_at}` });
    }
    return out;
  }
  if (phase === "running" && host && gpus.length > 0) {
    const held = host.gpus.filter((g) => gpus.includes(g.index));
    if (held.length > 0) {
      const util = held.reduce((sum, g) => sum + g.util, 0) / held.length;
      const mem = held.reduce((sum, g) => sum + g.mem_used_mb, 0) / 1024;
      out.push({
        label: "GPU",
        value: String(Math.round(util)),
        unit: "%",
        tooltip: `mean utilization of GPU ${gpus.join(", ")}`,
      });
      out.push({ label: "mem", value: String(Math.round(mem)), unit: "GB", tooltip: "GPU memory in use" });
    }
  }
  if ((phase === "running" || phase === "stale") && gpus.length > 0 && !record.cost) {
    const wall = runSeconds(record, now);
    if (wall !== null) {
      out.push({
        label: "GPU h",
        value: ((wall * gpus.length) / 3600).toFixed(2),
        tooltip: `wall × ${gpus.length} GPU; the cost is set when the run ends`,
      });
    }
  }
  if (phase === "stale" && host) {
    const gone = secondsSince(host.state.since, now);
    if (gone !== null) {
      out.push({
        label: "unreachable",
        value: fmtWait(gone),
        tooltip: `no answer from ${name} since ${host.state.since}`,
      });
    }
  }
  return out;
}
