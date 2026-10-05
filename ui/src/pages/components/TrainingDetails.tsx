/** Training records: checkpoint validation and run-level evaluations stay separate. */
import { useQueries, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, request, ROUTES } from "../../api/client";
import type { Artifact, PanelSpec, RunRecord, ScoreRecord, ViewQueryBody } from "../../api/models";
import { queryKeys, useTask } from "../../api/queries";
import { AppLink, hrefs, isPlainClick } from "./links";
import { latestScores } from "./ScoresList";

export const TRAINING_PAGE_SIZE = 20;
const DASH = "—";
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const numberText = (value: unknown): string => finite(value) ? String(value) : DASH;

/** Render exactly the metrics recorded on checkpoints, including zero and absent fields. */
export function CheckpointTable({ artifacts }: { artifacts: readonly Artifact[] }) {
  const checkpoints = artifacts.filter(artifact => artifact.kind === "checkpoint");
  const names = [...new Set(checkpoints.flatMap(artifact => Object.keys(artifact.metrics)))].sort();
  if (!checkpoints.length) return <p className="small">No checkpoints recorded.</p>;
  return <div style={{ overflowX: "auto" }}>
    <table className="sw-runs" aria-label="Checkpoint metrics">
      <thead><tr><th scope="col">Step</th><th scope="col">Path</th>{names.map(name => <th scope="col" key={name}>{name}</th>)}</tr></thead>
      <tbody>{checkpoints.map((artifact, index) => <tr key={`${artifact.host}:${artifact.path}:${index}`}>
        <td>{numberText(artifact.step)}</td>
        <td style={{ overflowWrap: "anywhere" }}>{artifact.host ? `${artifact.host}:` : ""}{artifact.path}</td>
        {names.map(name => <td key={name}>{numberText(artifact.metrics[name])}</td>)}
      </tr>)}</tbody>
    </table>
    <p className="small">Recorded checkpoint metrics; val/* are validation measurements. Run-level evaluated scores are shown separately.</p>
  </div>;
}

interface TrainingProps {
  project: string;
  task: string;
  onSelectRun?: (runId: string) => void;
}
interface Cursor { createdAt: string; runId: string }

function useTrainingPage(project: string, task: string) {
  const [cursors, setCursors] = useState<Cursor[]>([]);
  const cursor = cursors.at(-1);
  const query = useQuery({
    queryKey: ["runs", "training-page", project, task, cursor ?? null],
    queryFn: ({ signal }) => request<RunRecord[]>("GET", ROUTES.runs, {
      query: { project, task, limit: TRAINING_PAGE_SIZE + 1, before_created_at: cursor?.createdAt, before_run_id: cursor?.runId }, signal,
    }),
  });
  const runs = (query.data ?? []).slice(0, TRAINING_PAGE_SIZE);
  const last = runs.at(-1);
  return {
    query, runs, page: cursors.length + 1,
    hasNext: (query.data?.length ?? 0) > TRAINING_PAGE_SIZE,
    previous: () => setCursors(previous => previous.slice(0, -1)),
    next: () => { if (last) setCursors(previous => [...previous, { createdAt: last.created_at, runId: last.run_id }]); },
  };
}

function Pager({ state }: { state: ReturnType<typeof useTrainingPage> }) {
  return <nav aria-label="Training run pages" style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12 }}>
    <button type="button" className="btn" disabled={state.page === 1 || state.query.isFetching} onClick={state.previous}>Previous page</button>
    <span className="small">Page {state.page} · {state.runs.length} runs · newest first</span>
    <button type="button" className="btn" disabled={!state.hasNext || state.query.isFetching} onClick={state.next}>Next page</button>
  </nav>;
}

function RunLink({ run, onSelectRun }: { run: RunRecord; onSelectRun?: TrainingProps["onSelectRun"] }) {
  return <AppLink href={hrefs.run(run.run_id)} title={run.hypothesis} onClick={event => {
    if (onSelectRun && isPlainClick(event)) { event.preventDefault(); onSelectRun(run.run_id); }
  }}>{run.run_id}</AppLink>;
}

/** Task checkpoints, paged by run; no history or individual run-detail requests. */
export function TrainingCheckpoints(props: TrainingProps) {
  return <TrainingCheckpointPage key={JSON.stringify([props.project, props.task])} {...props} />;
}

function TrainingCheckpointPage({ project, task, onSelectRun }: TrainingProps) {
  const state = useTrainingPage(project, task);
  if (state.query.isPending) return <p role="status" className="small">Loading checkpoints…</p>;
  if (state.query.isError) return <div><p role="alert">Could not load checkpoints: {state.query.error.message}</p><Pager state={state} /></div>;
  return <div>
    {!state.runs.length ? <p className="small">No training runs recorded.</p> : state.runs.map(run => <section key={run.run_id} style={{ marginBottom: 16 }}>
      <h3><RunLink run={run} onSelectRun={onSelectRun} /></h3>
      <CheckpointTable artifacts={run.artifacts} />
    </section>)}
    <Pager state={state} />
  </div>;
}

/** Task training runs, with at most twenty score-detail requests and one scoped history query per page. */
export function TrainingRuns(props: TrainingProps) {
  return <TrainingRunsPage key={JSON.stringify([props.project, props.task])} {...props} />;
}

function evaluatedScore(scores: ScoreRecord[], version: string | undefined, key: string): ScoreRecord | undefined {
  if (!version) return undefined;
  const current = latestScores(scores).filter(score => score.metric === "top1" && score.version === version);
  const selected = current.find(score => score.key === key);
  // Failed reevaluation appends a metric-wide '*' row, leaving older key rows intact.
  // Equal timestamps also favor the failure: the evaluator can emit both in one batch.
  const failure = current.find(score => score.key === "*" && score.error !== null);
  return failure && (!selected || failure.created_at >= selected.created_at) ? failure : selected;
}

function ScoreCell({ score, loading, error }: { score?: ScoreRecord; loading: boolean; error: boolean }) {
  if (error) return <td title="Evaluated scores could not be loaded">unavailable</td>;
  if (loading) return <td aria-label="Loading evaluated score">…</td>;
  if (score?.error) return <td title={score.error}>error</td>;
  return <td title={score ? `top1@${score.version}/${score.key}` : "No evaluated score recorded for the current metric version"}>{numberText(score?.value)}</td>;
}

function TrainingRunsPage({ project, task, onSelectRun }: TrainingProps) {
  const state = useTrainingPage(project, task);
  const taskQuery = useTask(project, task);
  const ids = state.runs.map(run => run.run_id);
  const details = useQueries({ queries: ids.map(runId => ({
    queryKey: queryKeys.run(runId), queryFn: ({ signal }: { signal: AbortSignal }) => api.run(runId, signal),
  })) });
  const metadataReady = details.every(detail => !detail.isPending);
  const historyIds = ids.filter((_, index) => details[index]?.isSuccess);
  const names = [...new Set(details.flatMap(detail => detail.isSuccess ? detail.data.metric_names : []))];
  // Every observed metric contributes to last step, including custom names. Preserve
  // the full discovered union, split at the API's 100-name cap, in one request.
  // Curves restrict run IDs before reading history; two endpoints preserve last values.
  const panels: PanelSpec[] = [];
  for (let index = 0; index < names.length; index += 100) {
    panels.push({ type: "curves", title: "Training observations", data: {
      metrics: names.slice(index, index + 100), filter: { run_id: historyIds }, group_by: "run", max_points: 2,
    } });
  }
  const body: ViewQueryBody = { view: { title: "Training observations", panels } };
  const hasHistory = panels.length > 0;
  const history = useQuery({
    queryKey: queryKeys.viewQuery(project, task, body),
    queryFn: ({ signal }) => api.queryView(project, task, body, signal),
    enabled: metadataReady && hasHistory,
  });
  const observations = history.data?.panels.flatMap(panel => panel.rows) ?? [];
  const historyError = hasHistory && (history.isError || Boolean(history.data?.panels.some(panel => panel.meta.error)));
  const historyLoading = !metadataReady || (hasHistory && history.isPending);
  const version = taskQuery.data?.summary.metrics.top1;
  if (state.query.isPending) return <p role="status" className="small">Loading training runs…</p>;
  if (state.query.isError) return <div><p role="alert">Could not load training runs: {state.query.error.message}</p><Pager state={state} /></div>;
  return <div>
    {historyError ? <p role="alert" className="small">Training observations could not be loaded.</p> : null}
    {taskQuery.isError ? <p role="alert" className="small">Current metric version could not be loaded.</p> : null}
    {!state.runs.length ? <p className="small">No training runs recorded.</p> : <div style={{ overflowX: "auto" }}>
      <table className="sw-runs" aria-label="Training runs">
        <thead><tr>
          <th scope="col">Run</th><th scope="col">Seed</th><th scope="col">Status</th>
          <th scope="col" title="Largest observed step across recorded metric histories">Last observed step</th>
          <th scope="col" title="Step of the recorded checkpoint with highest val/top1; first recorded wins ties">Best checkpoint step (val/top1)</th>
          <th scope="col" title={`Run-level evaluated top1${version ? `@${version}` : ""}/value`}>Top1 best (evaluated)</th>
          <th scope="col" title={`Run-level evaluated top1${version ? `@${version}` : ""}/final`}>Top1 final (evaluated)</th>
          <th scope="col" title="Last recorded sys/gpu_util measurement">GPU % (last)</th>
          <th scope="col" title="Last recorded sys/gpu_mem_gb measurement">Memory GB (last)</th>
          <th scope="col">Host</th>
        </tr></thead>
        <tbody>{state.runs.map((run, index) => {
          const points = observations.filter(point => point.run_id === run.run_id && finite(point.step));
          const lastStep = points.reduce<number | null>((last, point) => Math.max(last ?? -Infinity, point.step as number), null);
          const latest = (name: string) => points.filter(point => point.name === name).sort((a, b) => (b.step as number) - (a.step as number))[0];
          const gpu = latest("sys/gpu_util");
          const memory = latest("sys/gpu_mem_gb");
          const bestCheckpoint = run.artifacts.filter(artifact => artifact.kind === "checkpoint" && finite(artifact.metrics["val/top1"]))
            .reduce<Artifact | undefined>((best, artifact) => !best || artifact.metrics["val/top1"]! > best.metrics["val/top1"]! ? artifact : best, undefined);
          const detail = details[index];
          const scoreLoading = Boolean(detail?.isPending) || taskQuery.isPending;
          const scoreError = Boolean(detail?.isError) || taskQuery.isError;
          const metricText = (value: unknown) => historyError || detail?.isError ? "unavailable" : historyLoading ? "…" : numberText(value);
          return <tr key={run.run_id}>
            <td><RunLink run={run} onSelectRun={onSelectRun} /></td>
            <td>{run.seed ?? DASH}</td><td>{run.status}</td>
            <td>{metricText(lastStep)}</td><td>{numberText(bestCheckpoint?.step)}</td>
            <ScoreCell score={evaluatedScore(detail?.data?.scores ?? [], version, "value")} loading={scoreLoading} error={scoreError} />
            <ScoreCell score={evaluatedScore(detail?.data?.scores ?? [], version, "final")} loading={scoreLoading} error={scoreError} />
            <td title={gpu ? `sys/gpu_util at step ${gpu.step}` : undefined}>{metricText(gpu?.value)}</td>
            <td title={memory ? `sys/gpu_mem_gb at step ${memory.step}` : undefined}>{metricText(memory?.value)}</td>
            <td>{run.host || DASH}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
    <p className="small">Best step uses recorded checkpoint validation top1. Evaluated scores use {version ? `top1@${version}` : "the current top1 version"}; missing measurements remain blank. GPU and memory show last recorded observations.</p>
    <Pager state={state} />
  </div>;
}
