/**
 * Run panel "Queue" for a run waiting on an SSH host (spec 8A.5; mockup shot-run-queued):
 * the host's GPUs (held by a run, used outside hx, or free) and its hx queue in order.
 * The GPU cells are the hosts grid's (`gpuCells` in HostsPanel), so both read a GPU alike.
 */
import { DASH, firstClause, isAgent, shortId } from "./format";
import { type CellKind, gpuCells, gpuRange, meanUtil } from "./HostsPanel";
import { AppLink, hrefs } from "./links";
import { fmtWait, secondsSince } from "./remote";
import type { HostRow, RunRecord, RunsQuery } from "./types";

/**
 * The runs query the panel reads (through `useAllRuns`, so the queue head is never cut off):
 * the queued runs of one environment, i.e. one host.
 */
export function queuedRunsQuery(environmentId: string): Omit<RunsQuery, "limit"> {
  return { status: "queued", environment_id: environmentId };
}

export interface QueueRow {
  position: number | null;
  runId: string;
  label: string;
  createdBy: string;
  gpus: number;
  waiting: string;
}

const LAST = Number.MAX_SAFE_INTEGER;

/**
 * The queued runs of one host, in queue order. A host serves one environment, so runs are
 * kept by `environment_id` (never `executor.host`, the machine's hostname), also when the
 * hub already filtered them. `current` (the page's own run) is kept when it is queued on
 * this host but missing from `runs`, which were read before it was indexed.
 */
export function queueRows(
  runs: readonly RunRecord[],
  environmentId: string,
  now: number = Date.now(),
  current?: RunRecord,
): QueueRow[] {
  const mine = (r: RunRecord): boolean => r.status === "queued" && r.environment_id === environmentId;
  const listed = runs.filter(mine);
  if (current !== undefined && mine(current) && !listed.some((r) => r.run_id === current.run_id)) {
    listed.push(current);
  }
  return listed
    .map((r) => {
      const waited = secondsSince(r.created_at, now);
      return {
        position: r.executor.queue_position ?? null,
        runId: r.run_id,
        label: firstClause(r.hypothesis, `run ${shortId(r.run_id)}`),
        createdBy: r.created_by,
        gpus: r.gpus_requested ?? 0,
        waiting: waited === null ? DASH : fmtWait(waited),
      };
    })
    .sort((a, b) => (a.position ?? LAST) - (b.position ?? LAST));
}

/** The queue's class for a hosts-grid cell kind: any hx run, a process outside hx, or free. */
type QueueCellKind = "run" | "ext" | "free";

function queueKind(kind: CellKind): QueueCellKind {
  return kind === "free" ? "free" : kind === "other" ? "ext" : "run";
}

const CELL_TIP: Record<QueueCellKind, string> = { run: "hx run", ext: "process outside hx", free: "free" };

/** No run records here: every hx run reads `run` (the hosts grid's unknown-launcher kind). */
const NO_RUNS: ReadonlyMap<string, RunRecord> = new Map();

export interface QueuePanelProps {
  host: HostRow | null;
  hostName: string;
  runId: string;
  rows: QueueRow[];
}

export function QueuePanel({ host, hostName, runId, rows }: QueuePanelProps) {
  const cells = host ? gpuCells(host.gpus, NO_RUNS) : [];
  return (
    <div className="queue">
      {cells.length > 0 ? (
        <ol className="gpu-cells" aria-label={`GPUs on ${hostName}`}>
          {cells.map((c) => {
            const kind = queueKind(c.kind);
            const util = meanUtil(c);
            return (
              <li
                key={c.index}
                className={`c ${kind}`}
                style={c.span > 1 ? { gridColumn: `span ${c.span}` } : undefined}
                title={`${gpuRange(c)}: ${CELL_TIP[kind]}, ${util}% busy`}
              >
                {c.runId ? shortId(c.runId) : kind}
                <small>{c.span > 1 ? `${util}% ×${c.span}` : `${util}%`}</small>
              </li>
            );
          })}
        </ol>
      ) : null}
      {rows.length === 0 ? (
        <p className="panel-empty">{`No queued runs on ${hostName}`}</p>
      ) : (
        <table className="tbl queue-t">
          <thead>
            <tr>
              <th>pos</th>
              <th>run</th>
              <th>config</th>
              <th>by</th>
              <th className="r">GPUs</th>
              <th className="r">waiting</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const me = row.runId === runId;
              return (
                <tr key={row.runId} className={me ? "me" : undefined} aria-current={me ? "true" : undefined}>
                  <td>{row.position ?? DASH}</td>
                  <td>
                    {me ? (
                      <b>{shortId(row.runId)}</b>
                    ) : (
                      <AppLink href={hrefs.run(row.runId)}>{shortId(row.runId)}</AppLink>
                    )}
                  </td>
                  <td>{row.label}</td>
                  <td>
                    <span className={`who ${isAgent(row.createdBy) ? "agent" : "human"}`}>
                      <i />
                      {row.createdBy}
                    </span>
                  </td>
                  <td className="r">{row.gpus}</td>
                  <td className="r">{row.waiting}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
