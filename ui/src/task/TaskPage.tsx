/**
 * Task page (spec 4.2): header (name, kind tag, one facts line, Re-evaluate all) and tabs
 * Charts · Runs · Sweeps · Examples · saved views · + View, chosen by `?tab=`. The run
 * selection (`useRunSelection`) lives in the URL and every tab shares it. `New run` is the
 * top bar's (it opens `NewRun` from the best config on a task route).
 */
import { Fragment, type MouseEvent, type ReactElement, type ReactNode, useState } from "react";
import { api } from "../api/client";
import type { EvalReport, Leaderboard } from "../api/models";
import { RUN_EVENT_INVALIDATES, useLeaderboard, useProjectSweeps, useTask, useTaskRuns, useViews } from "../api/queries";
import { StatusIcon } from "../chrome/StatusIcon";
import { fmtScore } from "../pages/components/format";
import { AppLink, hrefs, isPlainClick, useNavigateHref } from "../pages/components/links";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { ReevalSummary } from "../pages/components/ReevalSummary";
import { paramsText, sweepHref } from "../pages/components/SweepModel";
import { useAction } from "../pages/components/useAction";
import { ChartsTab } from "./ChartsTab";
import { ExamplesTab } from "./ExamplesTab";
import { type TaskFacts, type TaskTab, boardWarnings, metricVersions, notFound, parseTab, sameTab, tabParam, taskFacts } from "./facts";
import { useRunSelection } from "./useRunSelection";
import { applySearch, useSearchState } from "./useSearchState";
import { ViewTab } from "./ViewTab";
import "./task.css";

export interface TaskPageProps {
  project: string;
  task: string;
}

/** Task-local state (reports) resets when project or task changes. */
export function TaskPage(props: TaskPageProps): ReactElement {
  return <TaskPageScope key={JSON.stringify([props.project, props.task])} {...props} />;
}

function TaskPageScope({ project, task }: TaskPageProps): ReactElement {
  const [params, setSearch] = useSearchState();
  const tab = parseTab(params);
  const runs = useTaskRuns(project, task);
  const board = useLeaderboard(project, task);
  const views = useViews(project, task);
  const detail = useTask(project, task);
  const data = runs.data;
  const [selection, setSelection] = useRunSelection({ sortDir: data?.higher_is_better === false ? "asc" : "desc" });
  const navigate = useNavigateHref();
  const [reevalReport, setReevalReport] = useState<EvalReport | null>(null);
  const reeval = useAction({
    send: (_: void, opts) => api.reevalTask(project, task, {}, opts),
    invalidate: RUN_EVENT_INVALIDATES,
    onSuccess: setReevalReport,
  });

  const gone = notFound(runs.error, board.error, views.error);
  if (gone) {
    return (
      <div className="task-page">
        <header className="task-head">
          <p className="crumb">
            <AppLink href={hrefs.overview()}>All projects</AppLink>
          </p>
          <h1>Not found</h1>
        </header>
        <ErrorBox error={gone} />
      </div>
    );
  }

  const go = (next: TaskTab): void => setSearch({ tab: tabParam(next), view: null }, { push: true });
  const hrefFor = (next: TaskTab): string =>
    `${hrefs.task(project, task)}${applySearch(params.toString(), { tab: tabParam(next), view: null })}`;
  const openRun = (runId: string): void => navigate(hrefs.run(runId));
  const custom = (views.data ?? []).filter((v) => v.origin !== "preset");
  const tabs: { tab: TaskTab; label: ReactNode; title?: string }[] = [
    { tab: { kind: "charts" }, label: "Charts" },
    { tab: { kind: "examples" }, label: "Examples" },
    ...custom.map((v) => ({ tab: { kind: "view", name: v.name } as TaskTab, label: v.title || v.name, title: v.path ?? `${v.origin} view` })),
  ];

  let body: ReactNode;
  if (tab.kind === "view") {
    body = (
      <ViewTab
        key={tab.name}
        project={project}
        task={task}
        name={tab.name}
        board={board.data}
        info={views.data?.find((v) => v.name === tab.name)}
      />
    );
  } else if (!data) {
    body = runs.isPending ? <Loading /> : null;
  } else if (tab.kind === "examples") {
    body = <ExamplesTab data={data} board={board.data} selection={selection} />;
  } else {
    body = (
      <ChartsTab
        project={project}
        task={task}
        data={data}
        board={board.data}
        selection={selection}
        onSelection={setSelection}
        onOpenRun={openRun}
      />
    );
  }

  return (
    <div className="task-page">
      <header className="task-head">
        <div className="title-row">
          <h1>{task}</h1>
          {data ? (
            <span className="tag" title="task kind">
              {data.kind}
            </span>
          ) : null}
          <span className="sp" />
          <button
            type="button"
            className="btn sm"
            disabled={reeval.pending}
            title="Re-score every run's saved predictions with the current metric versions"
            onClick={() => {
              setReevalReport(null);
              reeval.run();
            }}
          >
            Re-evaluate all
          </button>
        </div>
        {data ? <Facts facts={taskFacts(data)} board={board.data} dataset={detail.data?.dataset?.name} /> : null}
        <div className="tabs-row">
          <div className="tabs" role="tablist" aria-label="Task">
            {tabs.map(({ tab: t, label, title }) => (
              <TabLink key={tabParam(t) ?? "charts"} href={hrefFor(t)} selected={sameTab(t, tab)} title={title} onGo={() => go(t)}>
                {label}
              </TabLink>
            ))}
          </div>
          <AppLink className="tab-add" href={hrefs.edit(project, task, "new")} title="New view">
            + View
          </AppLink>
        </div>
      </header>
      {runs.error ? <ErrorBox error={runs.error} /> : null}
      {board.error ? <ErrorBox error={board.error} /> : null}
      {views.error ? <ErrorBox error={views.error} /> : null}
      {reeval.error ? <ErrorBox error={reeval.error} /> : null}
      {reevalReport ? <ReevalSummary report={reevalReport} /> : null}
      <SweepsLine project={project} />
      <div className="task-body">{body}</div>
    </div>
  );
}

interface TabLinkProps {
  href: string;
  selected: boolean;
  title?: string;
  onGo: () => void;
  children: ReactNode;
}

function TabLink({ href, selected, title, onGo, children }: TabLinkProps): ReactElement {
  return (
    <a
      role="tab"
      aria-selected={selected}
      className={selected ? "on" : undefined}
      href={href}
      title={title}
      onClick={(e: MouseEvent<HTMLAnchorElement>) => {
        if (!isPlainClick(e)) return;
        e.preventDefault();
        onGo();
      }}
    >
      {children}
    </a>
  );
}

function Facts({ facts, board, dataset }: { facts: TaskFacts; board: Leaderboard | undefined; dataset: string | undefined }): ReactElement {
  return (
    <p className="facts">
      {board?.metric_drift?.length ? (
        <span role="img" aria-label="Metric source drift" title={`Different stored metric source hashes: ${board.metric_drift.join(", ")}`}>
          ⚠
        </span>
      ) : null}
      <span title={board ? metricVersions(board) : undefined}>
        Primary <b>{facts.primary}</b> {facts.direction}
      </span>
      {facts.best ? (
        <span>
          Best <b className="ok">{fmtScore(facts.best.value)}</b>{" "}
          <AppLink href={hrefs.run(facts.best.runId)} title="Open the best run">
            {facts.best.name}
          </AppLink>
        </span>
      ) : null}
      <span>
        <b>{facts.runs}</b> runs · <b>{facts.configs}</b> configs
      </span>
      {facts.running > 0 ? (
        <StatusIcon status="running" label={`${facts.running} running`} />
      ) : null}
      {facts.queued > 0 ? (
        <StatusIcon status="queued" label={`${facts.queued} queued`} />
      ) : null}
      {dataset ? <span>{dataset}</span> : null}
      {board ? boardWarnings(board).map((text) => <span key={text} className="warn">{text}</span>) : null}
    </p>
  );
}

/**
 * The project's sweeps with their best config, each linking its sweep. Nothing while there
 * are none, or when the list fails. Replaced by the Sweeps tab in T7.
 */
function SweepsLine({ project }: { project: string }): ReactElement | null {
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
          {s.best && s.best.mean !== null ? ` ${paramsText(s.best.params, Object.keys(s.best.params))} ${fmtScore(s.best.mean)}` : ""}
        </Fragment>
      ))}
    </p>
  );
}
