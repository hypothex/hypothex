/**
 * Sweep screen (spec 8A.6, contract section 4, mockup shot-sweep-*): one-line headline
 * with the best cell, meta line, stat strip and progress strip; (a) params heat table
 * for two listed params, a sortable table otherwise; (b) seeds forest; (c) runs on hosts.
 * Actions: Copy as CLI, Cancel queued, Add seeds.
 */
import { useQuery } from "@tanstack/react-query";
import { type ReactElement, useState } from "react";
import { api } from "../api/client";
import type { HostRow, Leaderboard, RunRecord, RunStatus, RunsQuery, SweepSummary } from "../api/models";
import { queryKeys, useAllRuns, useHosts, useSweep } from "../api/queries";
import { Figure } from "./components/Figure";
import { fmtClock, isAgent, primaryMetricName } from "./components/format";
import { Unbroken } from "./components/Headline";
import { AppLink, hrefs } from "./components/links";
import { ErrorBox, Loading } from "./components/QueryState";
import { StatStrip } from "./components/StatStrip";
import { PageStyles } from "./components/styles";
import { SweepActions } from "./components/SweepActions";
import { SweepForest } from "./components/SweepForest";
import { SweepProgress } from "./components/SweepGlyphs";
import { SweepHeat } from "./components/SweepHeat";
import {
  type SweepCellRow,
  gridLabel,
  heatAxes,
  hostsOf,
  orderRuns,
  parseCell,
  parseCells,
  runState,
  seedValues,
  staleHosts,
  sweepStats,
} from "./components/SweepModel";
import { SweepRerun } from "./components/SweepRerun";
import { SweepRuns } from "./components/SweepRuns";
import { SweepStyles } from "./components/SweepStyles";
import { SweepTable } from "./components/SweepTable";

/**
 * `GET /api/v1/runs` query for every run of a sweep (its member tag `SweepSummary.tag`,
 * `sweep:<owner8>:<id>`, archived included). The UI never builds the tag: the owner part is
 * the hub's environment id. No limit: `useAllRuns` pages until it has them all.
 */
export function sweepRunsQuery(project: string, tag: string): Omit<RunsQuery, "limit"> {
  return { project, tag, archived: true };
}

export interface SweepPageProps {
  project: string;
  sweepId: string;
  /** Clock for ages, GPU-hours and ETA (tests pass a fixed time). */
  now?: number;
}

export function SweepPage({ project, sweepId, now }: SweepPageProps): ReactElement {
  const summary = useSweep(project, sweepId);
  const memberTag = summary.data?.tag; // the runs query waits for the summary's member tag
  const runs = useAllRuns(sweepRunsQuery(project, memberTag ?? ""), memberTag !== undefined);
  const hosts = useHosts();
  const task = summary.data?.spec.task ?? null;
  const board = useQuery({
    queryKey: queryKeys.leaderboard(project, task ?? "", []),
    queryFn: ({ signal }) => api.leaderboard(project, task ?? "", [], signal),
    enabled: task !== null,
  });
  return (
    <div className="page">
      <PageStyles />
      <SweepStyles />
      <p className="crumb">
        <AppLink href={hrefs.overview()}>{project}</AppLink>
        <span className="sep">/</span>
        {task !== null ? (
          <>
            <AppLink href={hrefs.task(project, task)}>{task}</AppLink>
            <span className="sep">/</span>
          </>
        ) : null}
        {`sweep ${sweepId}`}
      </p>
      {summary.error ? (
        <ErrorBox error={summary.error} />
      ) : summary.data ? (
        <SweepBody
          project={project}
          sweepId={sweepId}
          summary={summary.data}
          runs={runs.data?.runs ?? []}
          hosts={hosts.data}
          board={board.data}
          now={now ?? Date.now()}
        />
      ) : (
        <Loading />
      )}
      {runs.error && !summary.error ? <ErrorBox error={runs.error} /> : null}
    </div>
  );
}

interface SweepBodyProps {
  project: string;
  sweepId: string;
  summary: SweepSummary;
  runs: readonly RunRecord[];
  hosts: readonly HostRow[] | undefined;
  board: Leaderboard | undefined;
  now: number;
}

function SweepBody({ project, sweepId, summary, runs, hosts, board, now }: SweepBodyProps): ReactElement {
  const { spec, counts } = summary;
  const names = spec.grid.map((p) => p.name);
  const cells = parseCells(summary.cells);
  const best = parseCell(summary.best);
  const higherIsBetter = board?.higher_is_better ?? true;
  const metric = board ? primaryMetricName(board.primary) : "score";
  const version = board?.metric_versions[metric];
  const stale = staleHosts(hosts);
  // membership comes from the backend (`summary.run_ids`, derived from the runs tagged `summary.tag`)
  const ordered = orderRuns(runs, summary.run_ids);
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
  return (
    <>
      <div className="run-top">
        <div>
          <h1 className="headline">
            <Unbroken text={summary.headline} />
          </h1>
          <p className="metaline">
            <span title={`${cells.length} param combinations × ${maxSeeds} seeds`}>
              <b>{gridLabel(spec)}</b>
              {` = ${counts.total ?? 0}`}
            </span>
            {gpus > 0 ? <span>{`${gpus} GPU / run`}</span> : null}
            {hostList.length > 0 ? <span title="Hosts">{hostList.join(", ")}</span> : null}
            <span className={`who ${isAgent(spec.created_by) ? "agent" : "human"}`}>
              <i />
              {spec.created_by}
            </span>
            <span title={spec.created_at}>{`${fmtClock(spec.created_at)} UTC`}</span>
            <span className="tag" title="Sweep id">
              {spec.id}
            </span>
          </p>
        </div>
        <SweepActions
          project={project}
          sweepId={sweepId}
          spec={spec}
          queued={counts.queued ?? 0}
          cellCount={cells.length}
          runs={ordered}
          onRerun={() => setRerun(true)}
        />
      </div>
      {launched ? (
        <p className="small launched" role="status">{`Launched ${launched.n} on ${launched.host}`}</p>
      ) : null}
      <div className="sweep-stats">
        <StatStrip
          items={sweepStats({
            counts,
            totalUsd: summary.total_usd,
            best,
            names,
            metric,
            unit: board?.unit ?? "",
            runs: ordered,
            hosts,
            now,
          })}
        />
        <SweepProgress counts={counts} />
      </div>
      <div className="sw-grid">
        <Figure
          letter="a"
          title={`${metric} by ${(axes ? [axes.row, axes.col] : names).join(" × ")}`}
          aside="mean over seeds"
        >
          {axes ? (
            <SweepHeat
              axes={axes}
              cells={cells}
              best={best}
              metric={metric}
              higherIsBetter={higherIsBetter}
              maxSeeds={maxSeeds}
              stateOf={stateOf}
              seedsOf={seedsOf}
            />
          ) : (
            <SweepTable
              names={names}
              cells={cells}
              best={best}
              metric={metric}
              higherIsBetter={higherIsBetter}
              maxSeeds={maxSeeds}
              stateOf={stateOf}
            />
          )}
        </Figure>
        <Figure letter="b" title="Seeds, 95% CI" aside={metric}>
          <SweepForest
            cells={cells}
            best={best}
            names={names}
            metric={metric}
            axisLabel={version ? `${metric} ${version}` : metric}
            higherIsBetter={higherIsBetter}
            maxSeeds={maxSeeds}
            seedsOf={seedsOf}
          />
        </Figure>
      </div>
      <Figure letter="c" title="Runs on hosts" aside={`${running} running, ${queued} queued`}>
        <SweepRuns runs={ordered} names={names} stale={stale} hosts={hosts} now={now} />
      </Figure>
      {rerun ? (
        <SweepRerun
          project={project}
          spec={spec}
          best={best}
          runs={ordered}
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
