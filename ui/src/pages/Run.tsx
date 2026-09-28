/**
 * Run screen (spec 8.3.3): hypothesis as title, status, stat strip, the task kind's run
 * panels (spec 8.4), where everything is, scores by metric version, notes, and actions.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys, useRun, useRunTraces } from "../api/queries";
import { Figure, panelLetter } from "./components/Figure";
import { firstClause, shortId } from "./components/format";
import { KindPanels, kindPanelCount, readsTraces, runViewPanels } from "./components/KindPanels";
import { AppLink, hrefs } from "./components/links";
import { LogView } from "./components/LogView";
import { Notes } from "./components/Notes";
import { ErrorBox, Loading } from "./components/QueryState";
import { RunActions } from "./components/RunActions";
import { runStats } from "./components/runStats";
import { ScoresList, primaryRef } from "./components/ScoresList";
import { StatStrip } from "./components/StatStrip";
import { StatusLine } from "./components/StatusLine";
import { PageStyles } from "./components/styles";
import { WhereList } from "./components/WhereList";
import { Unbroken } from "./components/Headline";

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
}

const LONG_TITLE = 60;

export function RunPage({ runId, log, example }: RunPageProps) {
  const run = useRun(runId);
  const record = run.data?.record;
  const project = record?.project ?? "";
  const task = record?.task ?? "";
  const hasTask = task !== "";
  // The same keys as useTaskKind and useLeaderboard, but idle for a run without a task.
  const kind = useQuery({
    queryKey: queryKeys.taskKind(project, task),
    enabled: hasTask,
    queryFn: ({ signal }) => api.taskKind(project, task, signal),
  });
  const board = useQuery({
    queryKey: queryKeys.leaderboard(project, task),
    enabled: hasTask,
    queryFn: ({ signal }) => api.leaderboard(project, task, [], signal),
  });
  const kindSpecs = kind.data?.run_view ?? [];
  const traces = useRunTraces(runId, kindSpecs.some(readsTraces));

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
  const row = board.data?.rows.find((r) => r.run_ids.includes(runId)) ?? null;
  const primary = primaryRef(board.data ?? null, row);
  const specs = runViewPanels(kindSpecs, traces.data?.length);
  const stream = asLogStream(log);
  const label = row?.label ?? firstClause(record.hypothesis, `run ${shortId(runId)}`);
  const title = record.hypothesis || label;

  let next = 0;
  const logLetter = stream ? panelLetter(next++) : "";
  const kindStart = next;
  next += kindPanelCount(specs);
  const whereLetter = panelLetter(next++);
  const scoresLetter = panelLetter(next++);
  const notesLetter = panelLetter(next++);

  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">
        {project}
        <span className="sep">/</span>
        {hasTask ? (
          <>
            <AppLink href={hrefs.task(project, task)}>{task}</AppLink>
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
        <RunActions record={record} />
      </div>
      <StatusLine record={record} />
      <StatStrip items={runStats(detail, primary, row)} />
      {kind.error ? <ErrorBox error={kind.error} /> : null}
      {stream ? <LogView runId={runId} stream={stream} letter={logLetter} /> : null}
      {hasTask ? (
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
