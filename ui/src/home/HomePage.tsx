/**
 * Home (spec 4.1): status strip; Running now; Hosts; Tasks with best over time; Recent runs
 * with failures and "Open stderr". No identity swatches (colour is task-scoped); the
 * status icon carries the state. Replaces the Overview page.
 *
 * Running now shows elapsed time, the latest step and the latest primary value: runs
 * report no total, so there is no progress bar and no ETA (controller ruling on M27).
 */
import { Fragment, useState, type ReactElement } from "react";
import type { HostRow, OverviewSummary, RunRecord } from "../api/models";
import { useMe, useRuns, useHosts, useOverview } from "../api/queries";
import { Sparkline } from "../charts/Sparkline";
import { Avatar } from "../chrome/Avatar";
import { Launcher } from "../chrome/Launcher";
import { StatusIcon } from "../chrome/StatusIcon";
import { GpuCells } from "../hosts/GpuCells";
import { CopyButton } from "../pages/components/CopyButton";
import { fmtClock, fmtDate, fmtDelta, fmtScore, fmtScoreUnit, parseTime, runSeconds } from "../pages/components/format";
import { fmtMoney, gpuSpec, hostRowForRun, longStale, remoteRows, staleBannerHours, useNow } from "../pages/components/HostsPanel";
import { AppLink, hrefs } from "../pages/components/links";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { fmtWait } from "../pages/components/remote";
import { EmptyHome } from "./EmptyHome";
import { type RecentRow, type TaskRow, isEmptyHome, recentRows, runLabel, statusStrip, taskRows, utcDayStart } from "./homeModel";
import "./home.css";

/** `21:03` for today (UTC), else `Sep 26`. */
function when(iso: string, now: number): string {
  return parseTime(iso) >= utcDayStart(now) ? fmtClock(iso) : fmtDate(iso);
}

function RunningTable({ summary, hosts, now }: { summary: OverviewSummary; hosts: readonly HostRow[]; now: number }) {
  const running = summary.running.filter((r) => r.status === "running");
  if (running.length === 0) return <p className="muted">Nothing running</p>;
  return (
    <div className="tblwrap">
      <table className="t">
        <thead>
          <tr>
            <th>Run</th>
            <th>Task</th>
            <th className="num">Elapsed</th>
            <th className="num">Step</th>
            <th className="num">Latest</th>
            <th>Host</th>
            <th>Launcher</th>
          </tr>
        </thead>
        <tbody>
          {running.map((r) => {
            const p = summary.progress?.[r.run_id];
            const row = hostRowForRun(r, hosts);
            const state = row?.state.state === "stale" ? "stale" : "running";
            const elapsed = runSeconds(r, now);
            return (
              <tr key={r.run_id}>
                <td className="nm one-line">
                  <StatusIcon status={state} label={<AppLink href={hrefs.run(r.run_id)}>{runLabel(summary, r)}</AppLink>} />
                </td>
                <td className="ink2 one-line">{r.task ? <AppLink href={hrefs.task(r.project, r.task)}>{r.task}</AppLink> : r.project}</td>
                <td className="num muted">{elapsed === null ? "—" : fmtWait(elapsed)}</td>
                <td className="num muted">{p?.step ?? "—"}</td>
                <td className="num" title={p?.metric ?? undefined}>
                  {p?.value !== null && p?.value !== undefined ? fmtScore(p.value) : "—"}
                </td>
                <td className="one-line">{row?.name ?? r.host}</td>
                <td>
                  <Launcher who={r.created_by} />{r.owner && <span> @{r.owner}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HostRows({ hosts, runs }: { hosts: readonly HostRow[]; runs: ReadonlyMap<string, RunRecord> }) {
  if (hosts.length === 0) return <p className="muted">No hosts</p>;
  return (
    <div className="tblwrap">
      {hosts.map((h) => (
        <div key={h.name} className="hostrow">
          <div>
            <AppLink className="nm" href={hrefs.hosts()}>
              {h.name}
            </AppLink>
            <div className="muted">{h.name === "local" ? "hub" : `${h.kind}${gpuSpec(h.gpus) ? ` · ${gpuSpec(h.gpus)}` : ""}`}</div>
          </div>
          <GpuCells host={h} runs={runs} />
          <div className="num">{h.cost_today_usd > 0 ? fmtMoney(h.cost_today_usd) : "—"}</div>
        </div>
      ))}
    </div>
  );
}

function TasksTable({ rows }: { rows: TaskRow[] }) {
  if (rows.length === 0) return <p className="muted">No tasks</p>;
  return (
    <div className="tblwrap">
      <table className="t">
        <thead>
          <tr>
            <th>Task</th>
            <th>Project</th>
            <th>Kind</th>
            <th>Primary</th>
            <th className="num">Best</th>
            <th className="num">7-day Δ</th>
            <th>Best over time</th>
            <th className="num">Runs</th>
            <th>Now</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={`${t.project}/${t.task}`}>
              <td className="nm">
                <AppLink href={hrefs.task(t.project, t.task)}>{t.task}</AppLink>
              </td>
              <td className="ink2">
                <span className="proj">
                  <Avatar name={t.project} size="sm" />
                  {t.project}
                </span>
              </td>
              <td className="muted">{t.kind}</td>
              <td className="ink2">{`${t.metric} ${t.arrow}`}</td>
              <td className="num best">{fmtScoreUnit(t.best, t.unit)}</td>
              <td className={`num ${t.delta === null || t.delta === 0 ? "muted" : t.improved ? "delta-up" : "delta-dn"}`}>
                {t.delta === null || t.delta === 0 ? "—" : fmtDelta(t.delta)}
              </td>
              <td>
                {t.history.length >= 2 ? (
                  <Sparkline values={t.history} width={90} height={22} lowerIsBetter={!t.higherIsBetter} label={`best ${t.metric} over time`} />
                ) : null}
              </td>
              <td className="num">{t.runs}</td>
              <td>
                {t.running > 0 ? (
                  <StatusIcon status="running" label={`${t.running} running`} />
                ) : t.queued > 0 ? (
                  <StatusIcon status="queued" label={`${t.queued} queued`} />
                ) : (
                  <span className="muted">idle</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecentTable({ rows, now }: { rows: RecentRow[]; now: number }) {
  if (rows.length === 0) return <p className="muted">No finished runs yet</p>;
  return (
    <div className="tblwrap">
      <table className="t">
        <thead>
          <tr>
            <th>Time</th>
            <th>Run</th>
            <th>Task</th>
            <th>Status</th>
            <th className="num">Score</th>
            <th className="num">Δ best</th>
            <th>Launcher</th>
            <th>Hypothesis</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.runId}>
              <td className="muted" title={r.at}>
                {when(r.at, now)}
              </td>
              <td className="nm one-line">
                <AppLink href={hrefs.run(r.runId)}>{r.name}</AppLink>
              </td>
              <td className="ink2 one-line">{r.task ? <AppLink href={hrefs.task(r.project, r.task)}>{r.task}</AppLink> : null}</td>
              <td>
                <StatusIcon status={r.status} label={r.count > 1 ? `${r.reason} ×${r.count}` : r.reason} />
                {r.retried ? <small className="muted"> · retry ok</small> : null}
              </td>
              <td className="num">{r.score === null ? "" : fmtScore(r.score)}</td>
              <td className="num muted">{r.deltaBest === null ? "" : fmtDelta(r.deltaBest)}</td>
              <td>{r.by ? <Launcher who={r.by} /> : null}{r.owner && <span> @{r.owner}</span>}</td>
              <td className="hyp ink2" title={r.hypothesis}>
                <span>{r.hypothesis}</span>
              </td>
              <td>
                {r.stderr ? (
                  <span className="fail-act">
                    <AppLink className="btn sm" href={hrefs.run(r.runId, { tab: "logs", log: "stderr" })}>
                      Open stderr
                    </AppLink>
                    <CopyButton text={r.stderr} label="stderr path" />
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HomePage(): ReactElement {
  const me=useMe();
  const [mine,setMine]=useState(false);
  const mineOn=mine && me.data?.auth === "on";
  const mineRuns=useRuns({owner:"me",status:"running"},{enabled:mineOn});
  const overview = useOverview();
  const hosts = useHosts();
  const now = useNow();
  if (overview.error) {
    return (
      <div className="home">
        <ErrorBox error={overview.error} />
      </div>
    );
  }
  if (!overview.data) {
    return (
      <div className="home">
        <Loading />
      </div>
    );
  }
  const summary = overview.data;
  if (isEmptyHome(summary)) return <EmptyHome />;
  // a failed hosts poll keeps the rest of Home; the Hosts section shows the error
  const rows = hosts.error ? [] : (hosts.data ?? []);
  const hours = staleBannerHours(rows);
  const gone = longStale(remoteRows(rows), now, hours);
  const runs = new Map(summary.running.map((r) => [r.run_id, r]));
  const running = summary.running.filter((r) => r.status === "running");
  const queued = summary.running.length - running.length;
  const runningSummary=mineOn ? {...summary,running:mineRuns.data ?? []} : summary;
  return (
    <div className="home">
      <div className="kpis">
        {statusStrip(summary, rows, now).map((k) => (
          <div key={k.label} className="kpi" title={k.title}>
            <div className="v">{k.value}</div>
            <div className="l">
              {k.status ? <StatusIcon status={k.status} iconOnly /> : null}
              {k.label}
            </div>
          </div>
        ))}
      </div>
      {gone.length > 0 ? (
        <p className="hosts-banner" role="status" title={`No answer for more than ${hours} h. Its runs stay stale, not lost: only the host marks a run lost.`}>
          {gone.map((h, i) => (
            <Fragment key={h.name}>
              {i > 0 ? ", " : null}
              <b>{h.name}</b>
              {` unreachable ${h.age}`}
            </Fragment>
          ))}
        </p>
      ) : null}
      <div className="two">
        <section aria-labelledby="home-running">
          <h2 id="home-running">
            Running now <span className="n">{`${runningSummary.running.filter(r=>r.status==="running").length} runs`}</span>
            {queued > 0 ? <AppLink href={hrefs.queue()}>{`${queued} queued`}</AppLink> : null}
          </h2>
          {me.data?.auth === "on" && <button className="btn sm" type="button" aria-pressed={mineOn} onClick={()=>setMine(v=>!v)}>Mine</button>}
          {mineOn && mineRuns.isPending ? <p role="status">Loading your running runs…</p> : mineOn && mineRuns.error ? <ErrorBox error={mineRuns.error}/> : <RunningTable summary={runningSummary} hosts={rows} now={now} />}
        </section>
        <section aria-labelledby="home-hosts">
          <h2 id="home-hosts">
            Hosts <span className="n">GPU use, live</span>
          </h2>
          {hosts.error ? <ErrorBox error={hosts.error} /> : <HostRows hosts={rows} runs={runs} />}
        </section>
      </div>
      <section aria-labelledby="home-tasks">
        <h2 id="home-tasks">
          Tasks <span className="n">best score per task, last 7 days</span>
        </h2>
        <TasksTable rows={taskRows(summary)} />
      </section>
      <section aria-labelledby="home-recent">
        <h2 id="home-recent">
          Recent runs <span className="n">all projects</span>
        </h2>
        <RecentTable rows={recentRows(summary)} now={now} />
      </section>
    </div>
  );
}
