/**
 * Run screen (spec 8.3.3, 8A.8): hypothesis as title (with the queue, stale or lost state
 * of a remote run), status, stat strip, the host queue of a queued run, the task kind's run
 * panels (spec 8.4), where everything is, placement on a host, scores by metric version,
 * notes, and actions.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useLostReason } from "../api/lostReasons";
import {
  HOSTS_REFETCH_MS,
  useAllRuns,
  useHosts,
  useLeaderboard,
  useRun,
  useRunTraces,
  useTaskKind,
} from "../api/queries";
import { Figure, panelLetter } from "./components/Figure";
import { useNow } from "./components/HostsPanel";
import { firstClause, shortId } from "./components/format";
import { Unbroken } from "./components/Headline";
import { KindPanels, kindPanelCount, readsTraces, runViewPanels } from "./components/KindPanels";
import { AppLink, hrefs } from "./components/links";
import { LogView } from "./components/LogView";
import { Notes } from "./components/Notes";
import { Placement, placementRows } from "./components/Placement";
import { ErrorBox, Loading } from "./components/QueryState";
import { QueuePanel, queueRows, queuedRunsQuery } from "./components/QueuePanel";
import { hostLabel, runHostRow, runPhase, stateTitle, sweepCrumb } from "./components/remote";
import { remoteStats } from "./components/remoteStats";
import { RemoteStyles } from "./components/remoteStyles";
import { RunActions } from "./components/RunActions";
import { runStats } from "./components/runStats";
import { ScoresList, primaryRef } from "./components/ScoresList";
import { StateBanner } from "./components/StateBanner";
import { StatStrip } from "./components/StatStrip";
import { StatusLine } from "./components/StatusLine";
import { PageStyles } from "./components/styles";
import { WhereList } from "./components/WhereList";

const LOG_STREAMS = ["stdout", "stderr", "supervisor"] as const;
type LogStream = (typeof LOG_STREAMS)[number];

/** Accept only the log streams the API serves (the value comes from the URL). */
export function asLogStream(value: unknown): LogStream | null {
  return LOG_STREAMS.find((s) => s === value) ?? null;
}

export interface RunPageProps {
  runId: string;
  log?: string;
  example?: string;
  /** How often the clock of an unfinished run ticks (waits, wall time, unreachable since). */
  clockMs?: number;
}

/** Clock tick of an unfinished run: its elapsed times move even when a poll returns the same data. */
export const RUN_CLOCK_MS = 10_000;

const LONG_TITLE = 60;

export function RunPage({ runId, log, example, clockMs = RUN_CLOCK_MS }: RunPageProps) {
  const run = useRun(runId);
  const lostWhy = useLostReason(runId);
  const record = run.data?.record;
  const project = record?.project ?? "";
  const task = record?.task ?? "";
  const hasTask = task !== "";
  // Idle for a run without a task.
  const kind = useTaskKind(project, task, { enabled: hasTask });
  const board = useLeaderboard(project, task, [], { enabled: hasTask });
  const kindSpecs = kind.data?.run_view ?? [];
  const traces = useRunTraces(runId, kindSpecs.some(readsTraces));
  const phase = run.data ? runPhase(run.data) : "local";
  // A remote run: the hub reports its host's state. Hub runs have host_state null, even
  // though the backend sets executor.host (the machine's hostname) on every run.
  const remote = (run.data?.host_state ?? null) !== null;
  // The shared hosts query (keepLastKnown, one query function per key), idle for a hub run.
  const hosts = useHosts(HOSTS_REFETCH_MS, remote);
  // the whole queue of the run's host (every page), never the newest page of all hosts
  const queued = useAllRuns(queuedRunsQuery(record?.environment_id ?? ""), phase === "queued");
  // the hub's descriptor (the Overview's key): its id says whose sweep a run's tag names
  const hubEnv = useQuery({
    queryKey: ["environment"],
    enabled: Boolean(record?.sweep_id),
    queryFn: ({ signal }) => api.environment(signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const hubEnvId = hubEnv.data?.environment_id;
  // queued, running and stale runs show times since a moment; an ended run's times are fixed
  const now = useNow(clockMs, record !== undefined && record.ended_at === null);

  if (run.error) {
    return (
      <div className="page">
        <PageStyles />
        <ErrorBox error={run.error} />
      </div>
    );
  }
  if (!run.data || !record) {
    return (
      <div className="page">
        <PageStyles />
        <Loading />
      </div>
    );
  }

  const detail = run.data;
  // matched by environment_id; null without the hosts list (texts then use the hostname)
  const host = runHostRow(detail, hosts.data);
  const where = hostLabel(record, host);
  const waiting = phase === "queued" || phase === "pending";
  const row = board.data?.rows.find((r) => r.run_ids.includes(runId)) ?? null;
  const primary = primaryRef(board.data ?? null, row);
  const specs = runViewPanels(kindSpecs, traces.data?.length);
  const stream = asLogStream(log);
  const label = row?.label ?? firstClause(record.hypothesis, `run ${shortId(runId)}`);
  const title = stateTitle(label, phase, record, host) ?? (record.hypothesis || label);
  const stats = waiting
    ? remoteStats(record, phase, host, now)
    : [...runStats(detail, primary, row, now, host), ...remoteStats(record, phase, host, now)];
  const showKind = hasTask && !waiting;
  const sweep = sweepCrumb(record, typeof hubEnvId === "string" ? hubEnvId : null);

  let next = 0;
  const logLetter = stream ? panelLetter(next++) : "";
  const queueLetter = phase === "queued" ? panelLetter(next++) : "";
  const kindStart = next;
  if (showKind) next += kindPanelCount(specs);
  const whereLetter = panelLetter(next++);
  const placeLetter = remote ? panelLetter(next++) : "";
  const scoresLetter = panelLetter(next++);
  const notesLetter = panelLetter(next++);

  return (
    <div className="page">
      <PageStyles />
      <RemoteStyles />
      <p className="crumb">
        {project}
        <span className="sep">/</span>
        {hasTask ? (
          <>
            <AppLink href={hrefs.task(project, task)}>{task}</AppLink>
            <span className="sep">/</span>
          </>
        ) : null}
        {sweep ? (
          <>
            {sweep.href ? (
              <AppLink href={sweep.href}>{`sweep ${sweep.id}`}</AppLink>
            ) : (
              <span title={sweep.why ?? undefined}>{`sweep ${sweep.id}`}</span>
            )}
            <span className="sep">/</span>
          </>
        ) : null}
        {label}
        <span className="sep">/</span>
        {runId}
        {kind.data ? (
          <span className="tag" title="task kind">
            {kind.data.kind}
          </span>
        ) : null}
      </p>
      <div className="run-top">
        <h1 className={title.length > LONG_TITLE ? "headline long" : "headline"}>
          <Unbroken text={title} />
        </h1>
        <RunActions record={record} phase={phase} hostName={host?.name ?? null} />
      </div>
      <StatusLine record={record} phase={phase} host={host} now={now} />
      <StateBanner
        record={record}
        phase={phase}
        host={host}
        conn={detail.host_state ?? null}
        now={now}
        reason={lostWhy}
      />
      <StatStrip items={stats} />
      {kind.error ? <ErrorBox error={kind.error} /> : null}
      {stream ? <LogView runId={runId} stream={stream} letter={logLetter} /> : null}
      {phase === "queued" ? (
        <Figure letter={queueLetter} title="Queue" aside={host ? `${host.name}, ${host.queue} waiting` : where}>
          {queued.error ? (
            <ErrorBox error={queued.error} />
          ) : queued.data ? (
            <>
              <QueuePanel
                host={host}
                hostName={where}
                runId={runId}
                rows={queueRows(queued.data.runs, record.environment_id, now, record)}
              />
              {queued.data.complete ? null : (
                <p className="small">{`first ${queued.data.runs.length} queued runs on ${where}`}</p>
              )}
            </>
          ) : (
            <Loading />
          )}
        </Figure>
      ) : null}
      {showKind ? (
        <KindPanels
          project={project}
          task={task}
          runId={runId}
          specs={specs}
          example={example}
          startIndex={kindStart}
        />
      ) : null}
      <div className="run-grid">
        <div>
          <Figure letter={whereLetter} title="Where" aside={<span title="host the run executed on">{record.host}</span>}>
            <WhereList detail={detail} />
          </Figure>
        </div>
        <div className="side">
          {remote ? (
            <Figure letter={placeLetter} title="Placement" aside={host?.kind ?? null}>
              <Placement rows={placementRows(record, phase, host)} />
            </Figure>
          ) : null}
          <Figure letter={scoresLetter} title="Scores">
            <ScoresList scores={detail.scores} metricNames={detail.metric_names} primary={primary} />
          </Figure>
          <Figure letter={notesLetter} title="Notes">
            <Notes runId={runId} notes={detail.notes} />
          </Figure>
        </div>
      </div>
    </div>
  );
}
