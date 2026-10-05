/**
 * The bar under a run's status line (spec 5.6; mockups shot-run-stale, shot-run-lost):
 * how long its host has been unreachable, or why the run is lost. Nothing otherwise.
 */
import { fmtTime } from "./format";
import { fmtWait, hostLabel, lostReason, type RunPhase, secondsSince } from "./remote";
import type { ConnState, HostRow, RunRecord } from "./types";

export interface StateBannerProps {
  record: RunRecord;
  phase: RunPhase;
  host: HostRow | null;
  conn: ConnState | null;
  now?: number;
  /** The `run.lost` event's reason, when this tab saw it (`useLostReason`). */
  reason?: string | null;
}

export function StateBanner({ record, phase, host, conn, now = Date.now(), reason = null }: StateBannerProps) {
  if (phase === "stale") {
    const name = hostLabel(record, host);
    const gone = host ? secondsSince(host.state.since, now) : null;
    return (
      <div className="state-bar" role="status">
        <b>{gone === null ? `${name} unreachable` : `${name} unreachable ${fmtWait(gone)}`}</b>
        {host ? <span>{`since ${fmtTime(host.state.since)}`}</span> : null}
        {host?.state.message ? <span>{host.state.message}</span> : null}
        <span className="r" title="connection state from the hub">
          {host?.state.state ?? conn ?? "stale"}
        </span>
      </div>
    );
  }
  if (phase === "lost") {
    const why = lostReason(record, reason);
    return (
      <div className="state-bar lost" role="status">
        <b title={why.tooltip}>{why.title}</b>
        {why.parts.map((part) => (
          <span key={part}>{part}</span>
        ))}
      </div>
    );
  }
  return null;
}
