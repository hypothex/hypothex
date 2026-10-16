/** Queue (spec 4.4): every queued run, grouped by host, in queue order, with a confirmed Stop. */
import type { ReactElement } from "react";
import { api } from "../api/client";
import { REMOTE_RUN_INVALIDATES, useAllRuns, useHosts } from "../api/queries";
import { Launcher } from "../chrome/Launcher";
import { StatusIcon } from "../chrome/StatusIcon";
import { DASH } from "../pages/components/format";
import { useNow } from "../pages/components/HostsPanel";
import { AppLink, hrefs } from "../pages/components/links";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { useAction } from "../pages/components/useAction";
import { useArmed } from "../run/useArmed";
import { GpuCells } from "./GpuCells";
import { type QueueGroup, queueGroups } from "./queueModel";
import "./hosts.css";

function QueueLine({ row }: { row: QueueGroup["rows"][number] }): ReactElement {
  const stop = useAction({ send: (_: void, opts) => api.cancelQueuedRun(row.runId, opts), invalidate: REMOTE_RUN_INVALIDATES });
  const { armed, arm, disarm } = useArmed([row.runId]);
  const r = row.record;
  return (
    <tr>
      <td className="num">{row.position ?? DASH}</td>
      <td className="nm">
        <AppLink href={hrefs.run(row.runId)}>{r.name ?? row.label}</AppLink>
      </td>
      <td className="ink2">{r.task ? <AppLink href={hrefs.task(r.project, r.task)}>{r.task}</AppLink> : r.project}</td>
      <td>
        <Launcher who={row.createdBy} />
      </td>
      <td className="num">{row.gpus}</td>
      <td className="num">{row.waiting}</td>
      <td>
        <StatusIcon status="queued" />
      </td>
      <td className="act">
        <button
          type="button"
          className="btn sm"
          disabled={stop.pending}
          onClick={() => {
            if (armed) {
              disarm();
              stop.run();
            } else arm();
          }}
          onBlur={disarm}
          onKeyDown={(e) => {
            if (e.key === "Escape") disarm();
          }}
          title={armed ? "Click again to remove it from the queue" : "Remove from the queue"}
        >
          {armed ? "Stop ✓?" : "Stop"}
        </button>
        {stop.error ? <ErrorBox error={stop.error} /> : null}
      </td>
    </tr>
  );
}

export function QueuePage(): ReactElement {
  const queued = useAllRuns({ status: "queued" });
  const hosts = useHosts();
  const now = useNow(10_000);
  const groups = queued.data ? queueGroups(queued.data.runs, hosts.data, now) : [];
  const total = groups.reduce((a, g) => a + g.rows.length, 0);
  return (
    <div className="hosts-page">
      <header className="ph">
        <h1>Queue</h1>
        {queued.data ? (
          <div className="facts">
            <span>{`${total} queued on ${groups.length} ${groups.length === 1 ? "host" : "hosts"}`}</span>
            {!queued.data.complete ? <span>{`first ${queued.data.runs.length}`}</span> : null}
          </div>
        ) : null}
      </header>
      {queued.error ? (
        <ErrorBox error={queued.error} />
      ) : !queued.data ? (
        <Loading />
      ) : groups.length === 0 ? (
        <p className="muted">Nothing queued</p>
      ) : (
        groups.map((g) => (
          <section key={g.key} aria-label={g.host} className="qgroup">
            <h2>
              {g.host} <span className="n">{`${g.rows.length} waiting`}</span>
            </h2>
            {g.row ? <GpuCells host={g.row} /> : null}
            <div className="tblwrap">
              <table className="t">
                <thead>
                  <tr>
                    <th className="num">Pos</th>
                    <th>Run</th>
                    <th>Task</th>
                    <th>Launcher</th>
                    <th className="num">GPUs</th>
                    <th className="num">Waiting</th>
                    <th>Status</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {g.rows.map((row) => (
                    <QueueLine key={row.runId} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))
      )}
    </div>
  );
}
