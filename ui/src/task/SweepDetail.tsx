/**
 * One sweep in the Sweeps tab (spec 4.2 "Sweeps"): header (id, grid shape, hosts, GPUs,
 * launcher, time, progress, Rerun sweep, Copy as CLI, Cancel queued, Add seeds, Resume),
 * the issuance state, the stat strip, then panels: parallel coordinates (one line per
 * finished run, sequential colour by the primary), mean per cell (heat table for two
 * params, sortable table otherwise), what matters, best cell against the next, runs on
 * hosts. Data and actions are those of the v4 sweep page.
 */
import { useQuery } from "@tanstack/react-query";
import { type ReactElement, useState } from "react";
import { api } from "../api/client";
import type { HostRow, Leaderboard, RunRecord, RunStatus, RunsQuery, SweepSummary, TaskRuns } from "../api/models";
import { queryKeys, useAllRuns, useHosts, useSweep } from "../api/queries";
import { Fit } from "../charts/Fit";
import { ParallelCoords } from "../charts/ParallelCoords";
import { Launcher } from "../chrome/Launcher";
import { Panel } from "../chrome/Panel";
import { fmtClock, fmtDelta, fmtInterval, fmtScore, primaryMetricName } from "../pages/components/format";
import { useNow } from "../pages/components/HostsPanel";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { StatStrip } from "../pages/components/StatStrip";
import { SweepActions } from "../pages/components/SweepActions";
import { SweepProgress } from "../pages/components/SweepGlyphs";
import { SweepHeat } from "../pages/components/SweepHeat";
import {
  type SweepCellRow,
  gridLabel,
  heatAxes,
  hostsOf,
  orderRuns,
  paramsText,
  parseCell,
  parseCells,
  runState,
  seedValues,
  staleHosts,
  sweepStats,
} from "../pages/components/SweepModel";
import { SweepRerun } from "../pages/components/SweepRerun";
import { SweepRuns } from "../pages/components/SweepRuns";
import { SweepTable } from "../pages/components/SweepTable";
import { SCORE_AXIS, bestComparison, parallelAxes, sweepLines, whatMatters } from "./sweepMath";

/**
 * `GET /api/v1/runs` for every run of a sweep: its member tag (`SweepSummary.tag`),
 * archived included, no limit (`useAllRuns` pages until it has them all).
 */
export function sweepRunsQuery(project: string, tag: string): Omit<RunsQuery, "limit"> {
  return { project, tag, archived: true };
}

export interface SweepDetailProps {
  project: string;
  sweepId: string;
  /** The task's runs (parallel coordinates, best-cell p); absent for a sweep without a task. */
  data?: TaskRuns;
  /** Clock for ages, GPU-hours and ETA (tests pass a fixed time). */
  now?: number;
}

export function SweepDetail({ project, sweepId, data, now }: SweepDetailProps): ReactElement {
  const summary = useSweep(project, sweepId);
  const memberTag = summary.data?.tag;
  const runs = useAllRuns(sweepRunsQuery(project, memberTag ?? ""), memberTag !== undefined);
  const hosts = useHosts();
  const tick = useNow();
  const task = summary.data?.spec.task ?? null;
  const board = useQuery({
    queryKey: queryKeys.leaderboard(project, task ?? "", []),
    queryFn: ({ signal }) => api.leaderboard(project, task ?? "", [], signal),
    enabled: task !== null,
  });
  return (
    <section className="sweep" aria-label={`Sweep ${sweepId}`}>
      {summary.data ? (
        <SweepBody
          project={project}
          sweepId={sweepId}
          summary={summary.data}
          runs={runs.data?.runs}
          runsError={runs.error}
          onRefresh={() => {
            void runs.refetch();
            void summary.refetch();
          }}
          hosts={hosts.data}
          board={board.data}
          data={data}
          now={now ?? tick}
        />
      ) : summary.error ? (
        <header className="sweep-head">
          <h2>{sweepId}</h2>
        </header>
      ) : (
        <Loading />
      )}
      {summary.error ? <ErrorBox error={summary.error} /> : null}
      {runs.error && runs.data !== undefined && !summary.error ? <ErrorBox error={runs.error} /> : null}
    </section>
  );
}

interface SweepBodyProps {
  project: string;
  sweepId: string;
  summary: SweepSummary;
  runs: readonly RunRecord[] | undefined;
  runsError: Error | null;
  onRefresh: () => void;
  hosts: readonly HostRow[] | undefined;
  board: Leaderboard | undefined;
  data: TaskRuns | undefined;
  now: number;
}

function SweepBody({ project, sweepId, summary, runs, runsError, onRefresh, hosts, board, data, now }: SweepBodyProps): ReactElement {
  const { spec, counts } = summary;
  const names = spec.grid.map((p) => p.name);
  const cells = parseCells(summary.cells);
  const best = parseCell(summary.best);
  const higherIsBetter = board?.higher_is_better ?? true;
  const metric = board ? primaryMetricName(board.primary) : "score";
  const stale = staleHosts(hosts);
  const ordered = orderRuns(runs ?? [], summary.run_ids);
  const byId = new Map(ordered.map((r) => [r.run_id, r]));
  const stateOf = (id: string, fallback: RunStatus | null) => runState(byId.get(id), fallback, stale);
  const seedsOf = (c: SweepCellRow): number[] => seedValues(c, board);
  const axes = heatAxes(spec);
  const gpus = ordered.find((r) => (r.gpus_requested ?? 0) > 0)?.gpus_requested ?? 0;
  const hostList = ordered.length > 0 ? hostsOf(ordered, hosts) : spec.host ? [spec.host] : [];
  const states = ordered.map((r) => runState(r, null, stale));
  const running = states.filter((s) => s === "running" || s === "stale").length;
  const queued = states.filter((s) => s === "queued").length;
  const maxSeeds = spec.seeds.length;
  const [rerun, setRerun] = useState(false);
  const [launched, setLaunched] = useState<{ host: string; n: number } | null>(null);
  const importance = whatMatters(cells, names);
  const comparison = bestComparison(cells, higherIsBetter);
  const lines = data ? sweepLines(data, spec) : [];
  const nextGroup = comparison?.next?.group_id ? data?.groups.find((g) => g.group_id === comparison.next?.group_id) : undefined;
  const bestIsTaskBest = comparison?.best.group_id ? data?.groups.find((g) => g.group_id === comparison.best.group_id)?.is_best === true : false;
  const p = bestIsTaskBest ? nextGroup?.vs_best?.p : undefined;
  return (
    <>
      <header className="sweep-head">
        <div className="sweep-title">
          <h2>{spec.id}</h2>
          <span title={`${cells.length} param combinations × ${maxSeeds} seeds`}>
            <b>{gridLabel(spec)}</b>
            {` = ${counts.total ?? 0}`}
          </span>
          {gpus > 0 ? <span>{`${gpus} GPU / run`}</span> : null}
          {runs === undefined ? (
            <span title="Hosts">{runsError ? "hosts unavailable" : "loading hosts…"}</span>
          ) : hostList.length > 0 ? (
            <span title="Hosts">{hostList.join(", ")}</span>
          ) : null}
          <Launcher who={spec.created_by} />
          <span title={spec.created_at}>{`${fmtClock(spec.created_at)} UTC`}</span>
          <SweepProgress counts={counts} />
        </div>
        <SweepActions
          project={project}
          sweepId={sweepId}
          spec={spec}
          queued={counts.queued ?? 0}
          issuance={summary.issuance}
          cellCount={cells.length}
          runs={ordered}
          onRerun={() => setRerun(true)}
        />
      </header>
      {summary.issuance ? (
        <div className="sweep-issuance" role="status">
          <p>
            {`Issuance ${summary.issuance.state} · ${counts.total ?? 0} observed / ${summary.issuance.planned} planned`}
            {summary.issuance.cancel_requested ? " · cancellation requested" : ""}
          </p>
          {summary.issuance.reason ? <p>{summary.issuance.reason.replaceAll("_", " ")}</p> : null}
          {summary.issuance.error ? <p role="alert">{`${summary.issuance.error.type}: ${summary.issuance.error.message}`}</p> : null}
          {summary.issuance.resume ? <p>{summary.issuance.resume.message}</p> : null}
        </div>
      ) : null}
      {launched ? <p className="small launched" role="status">{`Launched ${launched.n} on ${launched.host}`}</p> : null}
      <div className="sweep-stats">
        <StatStrip
          items={sweepStats({
            counts,
            totalUsd: summary.total_usd,
    costComplete: summary.cost_complete,
            best,
            names,
            metric,
            unit: board?.unit ?? "",
            runs: ordered,
            runsState: runs !== undefined ? undefined : runsError ? "error" : "loading",
            hosts,
            now,
          })}
        />
      </div>
      <div className="pgrid sweep-grid">
        {lines.length > 0 ? (
          <div className="wide">
            <Panel title="Parallel coordinates" unit={`one line per finished run · colour = ${metric}`}>
              <Fit>{(width) => <ParallelCoords width={width} axes={parallelAxes(spec, metric)} lines={lines} colorBy={SCORE_AXIS} higherIsBetter={higherIsBetter} />}</Fit>
            </Panel>
          </div>
        ) : null}
        <div className="wide">
          <Panel title={`Mean ${metric} per cell`} aside="mean over seeds">
            {axes ? (
              <SweepHeat axes={axes} cells={cells} best={best} metric={metric} higherIsBetter={higherIsBetter} maxSeeds={maxSeeds} stateOf={stateOf} seedsOf={seedsOf} />
            ) : (
              <SweepTable names={names} cells={cells} best={best} metric={metric} higherIsBetter={higherIsBetter} maxSeeds={maxSeeds} stateOf={stateOf} />
            )}
          </Panel>
        </div>
        <Panel title="What matters" unit={`share of ${metric} variance`}>
          {importance.length > 0 ? (
            <div className="wm">
              {importance.map((x) => (
                <div key={x.name} className="wm-row">
                  <span>{x.name}</span>
                  <span className="bar" aria-hidden="true">
                    <i style={{ width: `${(x.share * 100).toFixed(1)}%` }} />
                  </span>
                  <span className="num">{`${Math.round(x.share * 100)}%`}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No scored cells yet</p>
          )}
        </Panel>
        <Panel title="Best cell">
          {comparison ? (
            <dl className="kv">
              <dt>params</dt>
              <dd>{paramsText(comparison.best.params, names)}</dd>
              <dt>{metric}</dt>
              <dd>
                <b className="ok">{fmtScore(comparison.best.mean)}</b>
                {comparison.best.lo !== null && comparison.best.hi !== null ? ` 95% CI ${fmtInterval(comparison.best.lo, comparison.best.hi)}` : ""}
              </dd>
              {comparison.next && comparison.delta !== null ? (
                <>
                  <dt>vs next</dt>
                  <dd>
                    {`${fmtDelta(comparison.delta)} over ${paramsText(comparison.next.params, names)}`}
                    {typeof p === "number" ? `, p = ${p.toPrecision(2)}` : ""}
                    {comparison.overlap !== null ? <div className="muted">{comparison.overlap ? "intervals overlap" : "intervals separate"}</div> : null}
                  </dd>
                </>
              ) : null}
            </dl>
          ) : (
            <p className="muted">No scored runs yet</p>
          )}
        </Panel>
        <div className="wide">
          <Panel title="Runs on hosts" aside={runs === undefined ? "" : `${running} running, ${queued} queued`}>
            {runs === undefined ? (
              runsError ? <ErrorBox error={runsError} /> : <Loading />
            ) : (
              <SweepRuns runs={ordered} names={names} stale={stale} hosts={hosts} now={now} />
            )}
          </Panel>
        </div>
      </div>
      {rerun ? (
        <SweepRerun
          project={project}
          spec={spec}
          best={best}
          runs={runs === undefined ? undefined : ordered}
          runsError={runsError}
          onRefresh={onRefresh}
          onClose={() => setRerun(false)}
          onLaunched={(records, host) => {
            setRerun(false);
            setLaunched({ host, n: records.length });
          }}
        />
      ) : null}
    </>
  );
}
