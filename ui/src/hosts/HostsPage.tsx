/** Hosts (spec 4.4): every host with its state, version, GPU cells, queue, rate and cost; connect actions. */
import { Fragment, type ReactElement } from "react";
import { api } from "../api/client";
import type { HostRow, HostState } from "../api/models";
import { HOST_EVENT_INVALIDATES, useHosts, useHubEnvironment } from "../api/queries";
import {
  HostVersion,
  LOCAL_HOST,
  StateGlyph,
  fmtMoney,
  gpuSpec,
  hostStateTitle,
  longStale,
  remoteRows,
  staleBannerHours,
  stateWord,
  useNow,
} from "../pages/components/HostsPanel";
import { AppLink, hrefs } from "../pages/components/links";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { useAction } from "../pages/components/useAction";
import { GpuCells } from "./GpuCells";
import "./hosts.css";

function HostAction({ row }: { row: HostRow }): ReactElement | null {
  const connect = useAction<HostState>({ send: (_: void, opts) => api.connectHost(row.name, opts), invalidate: HOST_EVENT_INVALIDATES });
  const disconnect = useAction<HostState>({ send: (_: void, opts) => api.disconnectHost(row.name, opts), invalidate: HOST_EVENT_INVALIDATES });
  const st = row.state.state;
  const error = connect.error ?? disconnect.error;
  return (
    <>
      {st === "connected" ? (
        <button
          type="button"
          className="btn sm"
          disabled={disconnect.pending}
          onClick={() => disconnect.run()}
          title={`Stop talking to ${row.name}; its runs keep going`}
        >
          Disconnect
        </button>
      ) : st === "connecting" || st === "bootstrapping" ? (
        <button type="button" className="btn sm" disabled>
          Connecting
        </button>
      ) : (
        <button type="button" className="btn sm" disabled={connect.pending} onClick={() => connect.run()} title={`Try ${row.name} again now`}>
          {st === "disabled" ? "Connect" : "Reconnect"}
        </button>
      )}
      {error ? <ErrorBox error={error} /> : null}
    </>
  );
}

function HostLine({ row, hub, now }: { row: HostRow; hub: string | null; now: number }): ReactElement {
  const st = row.state.state;
  const local = row.name === LOCAL_HOST;
  const rate = row.usd_per_gpu_hour ?? null;
  return (
    <tr aria-label={row.name} className={st === "stale" ? "stale" : undefined}>
      <th scope="row">
        <b>{row.name}</b> <span className="tag">{local ? "hub" : row.kind}</span>
        <div className="muted" title={row.projects.join(", ")}>
          {gpuSpec(row.gpus) || "·"}
        </div>
      </th>
      <td>
        <span className="hst" title={hostStateTitle(row)}>
          <StateGlyph state={st} />
          {stateWord(row, now)}
        </span>
        <div className="muted">
          <HostVersion host={row.name} version={row.state.hx_version ?? null} hub={hub} />
        </div>
      </td>
      <td>
        <GpuCells host={row} />
      </td>
      <td className="num" title={row.queue > 0 ? `${row.queue} hx runs waiting for GPUs` : "Queue empty"}>
        {row.queue > 0 ? <AppLink href={hrefs.queue()}>{row.queue}</AppLink> : 0}
      </td>
      <td className="num" title={rate !== null ? "$/GPU-h from environments.yaml" : "No rate set"}>
        {rate !== null ? `$${rate.toFixed(2)}` : "·"}
      </td>
      <td className="num" title="GPU and API cost of runs today">
        {row.cost_today_usd > 0 ? fmtMoney(row.cost_today_usd) : "·"}
      </td>
      <td className="act">{local ? null : <HostAction row={row} />}</td>
    </tr>
  );
}

export function HostsPage(): ReactElement {
  const hosts = useHosts();
  const env = useHubEnvironment();
  const now = useNow();
  const reload = useAction({ send: (_: void, opts) => api.reloadHosts(opts), invalidate: HOST_EVENT_INVALIDATES });
  const hub = typeof env.data?.hx_version === "string" ? env.data.hx_version : null;
  const rows = hosts.data ?? [];
  const hours = staleBannerHours(rows);
  const gone = longStale(remoteRows(rows), now, hours);
  const usd = rows.reduce((a, h) => a + h.cost_today_usd, 0);
  return (
    <div className="hosts-page">
      <header className="ph">
        <h1>Hosts</h1>
        {hosts.data ? (
          <div className="facts">
            <span>{`${rows.length} ${rows.length === 1 ? "host" : "hosts"}`}</span>
            {hub ? <span>{`hub hx ${hub}`}</span> : null}
            <span>{`${fmtMoney(usd)} today`}</span>
          </div>
        ) : null}
        <button
          type="button"
          className="btn sm"
          disabled={reload.pending}
          onClick={() => reload.run()}
          title="Read environments.yaml again (after hx hosts add, map or rm)"
        >
          Reload
        </button>
      </header>
      {gone.length > 0 ? (
        <p
          className="hosts-banner"
          role="status"
          title={`No answer for more than ${hours} h. Its runs stay stale, not lost: only the host marks a run lost.`}
        >
          {gone.map((h, i) => (
            <Fragment key={h.name}>
              {i > 0 ? ", " : null}
              <b>{h.name}</b>
              {` unreachable ${h.age}`}
            </Fragment>
          ))}
        </p>
      ) : null}
      {reload.error ? <ErrorBox error={reload.error} /> : null}
      {hosts.error ? (
        <ErrorBox error={hosts.error} />
      ) : !hosts.data ? (
        <Loading />
      ) : (
        <div className="tblwrap">
          <table className="t hosts-t">
            <thead>
              <tr>
                <th>Host</th>
                <th>State</th>
                <th>GPUs</th>
                <th className="num">Queue</th>
                <th className="num">$/GPU-h</th>
                <th className="num">Today</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <HostLine key={row.name} row={row} hub={hub} now={now} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
