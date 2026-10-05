/**
 * Task screen (spec 8.3.2): the leaderboard's one-line headline, view tabs (the kind's
 * preset, custom views, `+ view`), and the active view's panels on a 12-column grid.
 * "New run" opens the Launch dialog (spec 8A.8), prefilled from the best config's latest
 * run: its command template, params and vars, and the next unused seeds of that config.
 * The template is the one at the click: live leaderboard updates never reset an open dialog.
 */
import { useQuery } from "@tanstack/react-query";
import { Fragment, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { EvalReport, RunRecord, ViewSpec } from "../api/models";
import {
  RUN_EVENT_INVALIDATES,
  queryKeys,
  useAllRuns,
  useLeaderboard,
  useProjectSweeps,
  useTask,
  useView,
  useViewQuery,
  useViews,
} from "../api/queries";
import { type LaunchDefaults, launchDefaults } from "../launch/draft";
import { LaunchDialog } from "../launch/LaunchDialog";
import { fmtScore, shortId } from "./components/format";
import { AppLink, hrefs, NavigateContext, useNavigateHref } from "./components/links";
import { PanelGrid } from "./components/PanelGrid";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";
import { paramsText, sweepHref } from "./components/SweepModel";
import type { Leaderboard } from "./components/types";
import { useAction } from "./components/useAction";
import { Unbroken } from "./components/Headline";
import { OpeningDialog } from "./components/OpeningDialog";
import { ReevalSummary } from "./components/ReevalSummary";
import { AgentIterationFlips, SystemRawSamples } from "./components/TaskInsights";
import { SelectedRun } from "./components/SelectedRun";
import { TrainingCheckpoints, TrainingRuns } from "./components/TrainingDetails";

export interface TaskPageProps {
  project: string;
  task: string;
  view?: string;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** The line under the headline: configs and runs, metric versions, re-eval backlog. */
export function boardMeta(board: Leaderboard): string[] {
  const runs = board.rows.reduce((n, row) => n + row.run_ids.length, 0);
  const out = [
    `${plural(board.rows.length, "config", "configs")}, ${plural(runs, "run", "runs")}`,
    ...Object.entries(board.metric_versions).map(([metric, version]) => `${metric} ${version}`),
  ];
  if (board.needs_reeval.length > 0) out.push(`${board.needs_reeval.length} need re-eval`);
  if (board.unscored.length > 0) out.push(`${board.unscored.length} unscored`);
  return out;
}

export { reevalLine } from "./components/ReevalSummary";

interface LaunchedRuns {
  host: string;
  records: RunRecord[];
}

interface NewRunProps {
  project: string;
  task: string;
  templateRunId: string | null;
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

interface Opened {
  repo: string;
  defaults: LaunchDefaults;
}

/**
 * Loads the repo path, the template run and every run of the task, archived included (not
 * only the newest page: an older or archived run may hold a seed), then shows the dialog.
 * What it opened with is kept until the dialog closes: a refetch (each launch invalidates
 * runs) or a failed refetch must not swap the dialog for a spinner or an error and lose
 * the session in it.
 */
function NewRun({ project, task, templateRunId, onClose, onLaunched }: NewRunProps) {
  const detail = useTask(project, task);
  const runs = useAllRuns({ project, task, archived: true });
  const template = useQuery({
    queryKey: queryKeys.run(templateRunId ?? ""),
    queryFn: ({ signal }) => api.run(templateRunId ?? "", signal),
    enabled: templateRunId !== null,
  });
  const opened = useRef<Opened | null>(null);
  if (opened.current === null) {
    // A failed runs read would propose seeds that already exist; a failed template read
    // would open a blank dialog without saying so. Both stop here instead.
    const error = detail.error ?? runs.error ?? template.error;
    if (error) return <OpeningDialog title="New run" error={error} onClose={onClose} onRetry={() => { void detail.refetch(); void runs.refetch(); if (templateRunId !== null) void template.refetch(); }} />;
    // a refetch in flight too: a cached list may predate runs started since (by anyone)
    if (
      detail.data === undefined ||
      runs.data === undefined ||
      runs.isFetching ||
      (templateRunId !== null && template.isPending)
    ) {
      return <OpeningDialog title="New run" onClose={onClose} />;
    }
    const all = runs.data;
    opened.current = {
      repo: detail.data.repo,
      defaults: launchDefaults(template.data?.record ?? null, all.runs, all.complete),
    };
  }
  const { repo, defaults } = opened.current;
  return (
    <LaunchDialog
      project={project}
      task={task}
      repo={repo}
      initial={defaults.draft}
      templateEnvironment={defaults.templateEnvironment}
      carry={defaults.carry}
      seedsNote={defaults.seedsNote}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  );
}

/** `Launched 3 on gpu1, 2 queued: f2c8 93e7 c2b9`, each id a link to its run. */
function LaunchedLine({ launched }: { launched: LaunchedRuns }) {
  const queued = launched.records.filter((r) => r.status === "queued").length;
  return (
    <p className="small launched" role="status">
      Launched {launched.records.length} on {launched.host}
      {queued > 0 ? `, ${queued} queued` : ""}:{" "}
      {launched.records.map((r, i) => (
        <Fragment key={r.run_id}>
          {i > 0 ? " " : ""}
          <AppLink href={hrefs.run(r.run_id)}>{shortId(r.run_id)}</AppLink>
        </Fragment>
      ))}
    </p>
  );
}

/**
 * The project's sweeps (spec 5.7: each sweep as a group with its best config): id linking
 * the sweep page, run count, best params and mean. Nothing while there are none, or when
 * the list fails (the rest of the page does not depend on it).
 */
function SweepsLine({ project }: { project: string }) {
  const sweeps = useProjectSweeps(project);
  const items = sweeps.data ?? [];
  if (items.length === 0) return null;
  return (
    <p className="small sweeps" aria-label="Sweeps" title={`Sweeps of project ${project}`}>
      sweeps:{" "}
      {items.map((s, i) => (
        <Fragment key={s.id}>
          {i > 0 ? " · " : ""}
          <AppLink href={sweepHref(project, s.id)} title={`${s.n_runs} runs, created ${s.created_at}`}>
            {s.id}
          </AppLink>
          {` ×${s.n_runs}`}
          {s.best && s.best.mean !== null
            ? ` ${paramsText(s.best.params, Object.keys(s.best.params))} ${fmtScore(s.best.mean)}`
            : ""}
        </Fragment>
      ))}
    </p>
  );
}

/** A 404 (unknown project), or the server's 400 `ConfigError` for an unknown task in a known project. */
const isGone = (e: Error | null): boolean =>
  e instanceof ApiError &&
  (e.status === 404 || (e.status === 400 && e.type === "ConfigError" && /^unknown task\b/.test(e.message)));

/** The first not-found among the task's own reads: the project or the task does not exist. */
function notFound(...errors: (Error | null)[]): Error | null {
  return errors.find(isGone) ?? null;
}

/** Task-local selections reset when project or task changes. */
export function TaskPage(props: TaskPageProps) {
  return <TaskPageScope key={JSON.stringify([props.project, props.task])} {...props} />;
}

function TaskPageScope({ project, task, view }: TaskPageProps) {
  const active = view ? String(view) : "overview";
  const [selectedPrimary, setSelectedPrimary] = useState<string | undefined>(undefined);
  const [seedVisibility, setSeedVisibility] = useState<boolean | undefined>(undefined);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const navigate = useNavigateHref();
  const baseline = useLeaderboard(project, task);
  const alternate = useLeaderboard(project, task, [], { primary: selectedPrimary, enabled: selectedPrimary !== undefined });
  const board = selectedPrimary === undefined ? baseline : alternate;
  const kind = baseline.data?.kind;
  const metricOptions = [...new Set([baseline.data?.primary, ...(baseline.data?.rows.flatMap(row => Object.keys(row.scores)) ?? [])])]
    .filter((ref): ref is string => !!ref && /^[^/@]+\/[^/@]+$/.test(ref) && ref.split("/")[0]! in (baseline.data?.metric_versions ?? {}));
  const selectHref = (href: string): void => {
    const match = /^\/r\/([^/?#]+)$/.exec(href);
    if (match && kind && ["training", "agent_eval", "agent_iteration", "system_bench"].includes(kind)) {
      try { setSelectedRun(decodeURIComponent(match[1]!)); return; } catch { /* malformed route keeps ordinary navigation */ }
    }
    navigate(href);
  };
  const views = useViews(project, task);
  const detail = useView(project, task, active);
  const leaderboardSpecs = detail.data?.view.panels?.filter(panel => panel.type === "leaderboard") ?? [];
  const authoredSeeds = leaderboardSpecs.every(panel => (panel.noise ?? ["seed", "test_set"]).includes("seed"));
  const showSeeds = seedVisibility ?? authoredSeeds;
  const customized = selectedPrimary !== undefined || seedVisibility !== undefined;
  const effectiveView: ViewSpec | undefined = detail.data ? {
    ...detail.data.view,
    panels: detail.data.view.panels?.map(panel => {
      const primary = selectedPrimary && ["leaderboard", "stat_strip", "curves"].includes(panel.type);
      const noise: ("seed" | "test_set")[] | undefined = panel.type === "leaderboard" && seedVisibility !== undefined
        ? [...(panel.noise ?? ["seed", "test_set"]).filter(value => value !== "seed"), ...(seedVisibility ? ["seed" as const] : [])]
        : undefined;
      return { ...panel, ...(primary ? { data: { ...panel.data, primary: selectedPrimary } } : {}), ...(noise ? { noise } : {}) };
    }),
  } : undefined;
  const panels = useViewQuery(project, task, customized ? effectiveView ? { view: effectiveView } : null : { name: active });
  const [reevalReport, setReevalReport] = useState<EvalReport | null>(null);
  const reeval = useAction({
    send: (_: void, opts) => api.reevalTask(project, task, {}, opts),
    invalidate: RUN_EVENT_INVALIDATES,
    onSuccess: setReevalReport,
  });
  // the template run at the click (`undefined`: closed); the leaderboard keeps changing
  const [launching, setLaunching] = useState<string | null | undefined>(undefined);
  const [launched, setLaunched] = useState<LaunchedRuns | null>(null);

  const info = views.data?.find((v) => v.name === active) ?? detail.data?.info;
  const editable = info !== undefined && info.origin !== "preset";
  const viewError = detail.error ?? panels.error;
  // `useViewQuery` keeps the last view's panels while the next loads; they must not be
  // drawn with the new view's specs, so wait for the active view's own data.
  const ready = panels.data !== undefined && !panels.isPlaceholderData && !detail.isPending && !board.isPending;
  const templateRunId = board.data?.rows[0]?.latest_run_id ?? null;
  const crumb = (
    <>
      <AppLink href={hrefs.overview()}>All projects</AppLink>
      <span className="sep">/</span>
      {project}
      <span className="sep">/</span>
      {task}
    </>
  );

  // one not-found state: no tabs or actions for a task that does not exist
  const gone = notFound(board.error, views.error);
  if (gone) {
    return (
      <div className="page">
        <PageStyles />
        <p className="crumb">{crumb}</p>
        <h1 className="headline">Not found</h1>
        <ErrorBox error={gone} />
      </div>
    );
  }

  return (
    <NavigateContext.Provider value={selectHref}>
    <div className="page">
      <PageStyles />
      <p className="crumb">
        {crumb}
        {board.data ? (
          <span className="tag" title="task kind">
            {board.data.kind}
          </span>
        ) : null}
      </p>
      <h1 className="headline">
        <Unbroken text={board.data?.headline ?? task} />
      </h1>
      {board.error ? <ErrorBox error={board.error} /> : null}
      {board.data ? (
        <p className="metaline">
          {board.data.metric_drift?.length ? <span role="img" aria-label="Metric source drift" title={`Different stored metric source hashes: ${board.data.metric_drift.join(", ")}`}>⚠</span> : null}
          {boardMeta(board.data).map((text) => (
            <span key={text}>{text}</span>
          ))}
        </p>
      ) : null}

      {baseline.data ? <div className="row" style={{ gap: 16, marginBottom: 12 }}>
        <label>Metric <select aria-label="Metric" value={selectedPrimary ?? baseline.data.primary} title="Ranking metric and primary summaries; authored plot axes remain unchanged" onChange={event => setSelectedPrimary(event.target.value === baseline.data?.primary ? undefined : event.target.value)}>
          {metricOptions.map(ref => <option key={ref} value={ref} title={`${ref} @ ${baseline.data?.metric_versions[ref.split("/")[0]!]}`}>{ref}</option>)}
        </select></label>
        {leaderboardSpecs.length > 0 ? <label title="Show individual seed or repeat dots on leaderboard plots">
          <input type="checkbox" aria-label={kind === "system_bench" ? "Repeats" : "Seeds"} checked={showSeeds} onChange={event => setSeedVisibility(event.target.checked === authoredSeeds ? undefined : event.target.checked)} />
          {kind === "system_bench" ? "Repeats" : "Seeds"}
        </label> : null}
      </div> : null}
      <nav className="view-tabs" aria-label="Views">
        {(views.data ?? []).map((v) => (
          <AppLink
            key={v.name}
            href={hrefs.task(project, task, v.name)}
            aria-current={v.name === active ? "page" : undefined}
            title={v.path ?? `${v.origin} view`}
          >
            {v.title || v.name}
            {v.origin === "preset" ? (
              <>
                {" "}
                <small>preset</small>
              </>
            ) : null}
          </AppLink>
        ))}
        <AppLink href={hrefs.edit(project, task, "new")} title="New view">
          + view
        </AppLink>
        <span className="r">
          {detail.data ? (
            <span className="small">{plural((detail.data.view.panels ?? []).length, "panel", "panels")}</span>
          ) : null}
          {editable ? (
            <AppLink className="btn" href={hrefs.edit(project, task, active)}>
              Edit
            </AppLink>
          ) : null}
          <button
            type="button"
            className="btn"
            onClick={() => {
              setReevalReport(null);
              reeval.run();
            }}
            disabled={reeval.pending}
            title="Re-score every run's saved predictions with the current metric versions"
          >
            Re-evaluate all
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={board.isPending || board.isError}
            onClick={() => setLaunching(templateRunId)}
            title="Launch runs of this task on any host"
          >
            New run
          </button>
        </span>
      </nav>
      {views.error ? <ErrorBox error={views.error} /> : null}
      {reeval.error ? <ErrorBox error={reeval.error} /> : null}
      {reevalReport ? (
        <ReevalSummary report={reevalReport} />
      ) : null}
      {launched ? <LaunchedLine launched={launched} /> : null}
      <SweepsLine project={project} />

      {viewError ? (
        <ErrorBox error={viewError} />
      ) : ready && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={customized ? effectiveView?.panels : detail.data?.view.panels} />
      ) : (
        <Loading />
      )}

      {kind === "training" ? <>
        <section className="fig" aria-label="Training run records"><h2>Training runs</h2><TrainingRuns project={project} task={task} onSelectRun={setSelectedRun} /></section>
        <section className="fig" aria-label="Training checkpoints"><h2>Checkpoints</h2><TrainingCheckpoints project={project} task={task} onSelectRun={setSelectedRun} /></section>
      </> : null}
      {kind === "agent_iteration" && board.data ? <AgentIterationFlips project={project} task={task} board={board.data} /> : null}
      {kind === "system_bench" ? <SystemRawSamples project={project} task={task} selectedRunId={selectedRun ?? undefined} /> : null}
      {selectedRun ? <SelectedRun runId={selectedRun} onClose={() => setSelectedRun(null)} /> : null}

      {launching !== undefined ? (
        <NewRun
          project={project}
          task={task}
          templateRunId={launching}
          onClose={() => setLaunching(undefined)}
          onLaunched={(records, host) => {
            setLaunching(undefined);
            setLaunched({ host, records });
          }}
        />
      ) : null}
    </div>
    </NavigateContext.Provider>
  );
}
