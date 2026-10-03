/** The line under a run's title: status, time, seed, launcher, where it runs, tags. */
import { fmtDuration, fmtTime, isAgent, runSeconds, shortId } from "./format";
import { AppLink, hrefs } from "./links";
import { fmtWait, freeGpus, hostLabel, type RunPhase, secondsSince } from "./remote";
import type { HostRow, RunRecord } from "./types";

/**
 * Where the run is, as short texts after the launcher: the machine's hostname for a hub run
 * (phase `local`); queue place and GPU need for a queued run; host with SLURM job or pid for
 * the rest. A remote host is named by `hostLabel` (the hub's name, else the hostname).
 */
export function placeParts(record: RunRecord, phase: RunPhase, host: HostRow | null): string[] {
  if (phase === "local") return [record.host];
  const name = hostLabel(record, host);
  const ex = record.executor;
  if (phase === "queued") {
    const pos = ex.queue_position ?? null;
    const where =
      pos === null ? `queued on ${name}` : host ? `${pos} of ${host.queue} on ${name}` : `${pos} in queue on ${name}`;
    const want = record.gpus_requested ?? 0;
    const need = host && host.gpus.length > 0 ? `needs ${want} GPU, ${freeGpus(host)} free` : `needs ${want} GPU`;
    return [where, need];
  }
  if (ex.slurm_job_id) return [`${name}, job ${ex.slurm_job_id}${phase === "pending" ? " pending" : ""}`];
  const pid = ex.child_pid ?? ex.pid;
  return pid !== null ? [`${name}, pid ${pid}`] : [name];
}

export interface StatusLineProps {
  record: RunRecord;
  phase?: RunPhase;
  host?: HostRow | null;
  now?: number;
}

export function StatusLine({ record, phase = "local", host = null, now = Date.now() }: StatusLineProps) {
  const stale = phase === "stale";
  const shown = stale ? "stale" : record.status;
  const seconds = runSeconds(record, now);
  const gone = stale && host ? secondsSince(host.state.since, now) : null;
  return (
    <p className="status">
      <span className={`st ${shown}`}>
        <i />
        {shown}
      </span>
      {stale ? (
        gone !== null ? (
          <span title="host unreachable for">{fmtWait(gone)}</span>
        ) : null
      ) : seconds !== null ? (
        <span>{fmtDuration(seconds)}</span>
      ) : null}
      {record.seed !== null ? <span>{`seed ${record.seed}`}</span> : null}
      <span title={record.created_at}>{fmtTime(record.created_at)}</span>
      <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
        <i />
        {record.created_by}
      </span>
      {placeParts(record, phase, host).map((text) => (
        <span key={text}>{text}</span>
      ))}
      {record.kind === "infer" ? (
        <span className="tag" title="inference-only run">
          infer
        </span>
      ) : null}
      {record.parent ? (
        <AppLink href={hrefs.run(record.parent)}>{`parent ${shortId(record.parent)}`}</AppLink>
      ) : null}
      {record.tags.map((tag) => (
        <span key={tag} className="tag">
          {tag}
        </span>
      ))}
    </p>
  );
}
