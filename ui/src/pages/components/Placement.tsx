/**
 * Run panel "Placement" (spec 8A.5, 8A.7; mockups shot-run-*): host, SLURM job and node,
 * GPUs as `CUDA_VISIBLE_DEVICES`, pid, queue place, and cost. Copy buttons copy the value.
 */
import { CopyButton } from "./CopyButton";
import { fmtClock } from "./format";
import { costShown, gpuLabel, hostLabel, type RunPhase, visibleDevices } from "./remote";
import type { HostRow, RunRecord } from "./types";

export interface PlaceRow {
  key: string;
  value: string;
  note?: string;
  copy?: string;
  mono?: boolean;
}

/** `host` is the run's hosts row (`runHostRow`), or null without the hosts list. */
export function placementRows(record: RunRecord, phase: RunPhase, host: HostRow | null): PlaceRow[] {
  const ex = record.executor;
  const name = hostLabel(record, host);
  const rows: PlaceRow[] = [
    { key: "Host", value: name, note: host?.kind ?? (ex.slurm_job_id ? "slurm" : "ssh"), copy: name },
  ];
  if (phase === "queued" || phase === "pending") {
    if (ex.slurm_job_id) {
      rows.push({ key: "Job", value: ex.slurm_job_id, note: "pending", copy: ex.slurm_job_id, mono: true });
    }
    const want = record.gpus_requested ?? 0;
    if (want > 0) rows.push({ key: "GPUs", value: gpuLabel(want, host), note: "assigned at start" });
    const pos = ex.queue_position ?? null;
    if (pos !== null) {
      rows.push({
        key: "Queue",
        value: host ? `${pos} of ${host.queue}` : String(pos),
        note: `since ${fmtClock(record.created_at)}`,
      });
    }
    return rows;
  }
  if (ex.slurm_job_id) rows.push({ key: "Job", value: ex.slurm_job_id, copy: ex.slurm_job_id, mono: true });
  if (ex.node) rows.push({ key: "Node", value: ex.node, copy: ex.node, mono: true });
  const gpus = ex.gpus ?? [];
  if (gpus.length > 0) {
    const cvd = visibleDevices(gpus);
    rows.push({ key: "GPUs", value: cvd, note: gpuLabel(gpus.length, host, gpus), copy: cvd, mono: true });
  }
  const pid = ex.child_pid ?? ex.pid;
  if (pid !== null) {
    const row: PlaceRow = { key: "PID", value: String(pid), mono: true };
    if (phase === "stale" && host) row.note = `as of ${fmtClock(host.state.since)}`;
    rows.push(row);
  }
  const cost = costShown(record.cost, host);
  if (cost) rows.push({ key: "Cost", value: cost.value, note: cost.note });
  return rows;
}

export function Placement({ rows }: { rows: PlaceRow[] }) {
  return (
    <div className="place">
      {rows.map((row) => (
        <div key={row.key} className="place-row">
          <span className="k">{row.key}</span>
          <span>
            <span className={row.mono ? "v mono" : "v"}>{row.value}</span>
            {row.note ? <small>{row.note}</small> : null}
          </span>
          {row.copy ? <CopyButton text={row.copy} label={`${row.key} ${row.copy}`} /> : <span />}
        </div>
      ))}
    </div>
  );
}
