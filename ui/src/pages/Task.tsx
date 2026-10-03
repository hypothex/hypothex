/**
 * Task screen (spec 8.3.2): the leaderboard's one-line headline, view tabs (the kind's
 * preset, custom views, `+ view`), and the active view's panels on a 12-column grid.
 * "New run" opens the Launch dialog (spec 8A.8), prefilled from the best config's latest
 * run: its command template, params and vars, and the next unused seeds of that config.
 */
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../api/client";
import type { RunRecord } from "../api/models";
import {
  RUN_EVENT_INVALIDATES,
  queryKeys,
  useLeaderboard,
  useRuns,
  useTask,
  useView,
  useViewQuery,
  useViews,
} from "../api/queries";
import { launchDefaults } from "../launch/draft";
import { LaunchDialog } from "../launch/LaunchDialog";
import { shortId } from "./components/format";
import { AppLink, hrefs } from "./components/links";
import { PanelGrid } from "./components/PanelGrid";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";
import type { Leaderboard } from "./components/types";
import { useAction } from "./components/useAction";
import { Unbroken } from "./components/Headline";

export interface TaskPageProps {
  project: string;
  task: string;
  view?: string;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/**
 * Runs read for the Launch dialog's defaults (used seeds of the template's config). The API
 * default of 200 would miss seeds on a big task and propose seeds that already exist.
 */
export const TASK_RUNS_LIMIT = 1000;

/** The line under the headline: configs and runs, metric versions, re-eval backlog. */
export function boardMeta(board: Leaderboard): string[] {
  const runs = board.rows.reduce((n, row) => n + row.run_ids.length, 0);
  const out = [
    `${plural(board.rows.length, "config", "configs")}, ${plural(runs, "run", "runs")}`,
    ...Object.entries(board.metric_versions).map(([metric, version]) => `${metric} ${version}`),
  ];
  if (board.needs_reeval.length > 0) out.push(`${board.needs_reeval.length} need re-eval`);
  return out;
}

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

/** Loads the repo path, the template run and the task's runs, then shows the dialog. */
function NewRun({ project, task, templateRunId, onClose, onLaunched }: NewRunProps) {
  const detail = useTask(project, task);
  const runs = useRuns({ project, task, limit: TASK_RUNS_LIMIT });
  const template = useQuery({
    queryKey: queryKeys.run(templateRunId ?? ""),
    queryFn: ({ signal }) => api.run(templateRunId ?? "", signal),
    enabled: templateRunId !== null,
  });
  if (detail.error) return <ErrorBox error={detail.error} />;
  if (detail.data === undefined || runs.isPending || (templateRunId !== null && template.isPending)) {
    return <Loading />;
  }
  const defaults = launchDefaults(template.data?.record ?? null, runs.data ?? []);
  return (
    <LaunchDialog
      project={project}
      task={task}
      repo={detail.data.repo}
      initial={defaults.draft}
      carry={defaults.carry}
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

export function TaskPage({ project, task, view }: TaskPageProps) {
  const active = view ? String(view) : "overview";
  const board = useLeaderboard(project, task);
  const views = useViews(project, task);
  const detail = useView(project, task, active);
  const panels = useViewQuery(project, task, { name: active });
  const reeval = useAction({
    send: (_: void, opts) => api.reevalTask(project, task, {}, opts),
    invalidate: RUN_EVENT_INVALIDATES,
  });
  const [launching, setLaunching] = useState(false);
  const [launched, setLaunched] = useState<LaunchedRuns | null>(null);

  const info = views.data?.find((v) => v.name === active) ?? detail.data?.info;
  const editable = info !== undefined && info.origin !== "preset";
  const viewError = detail.error ?? panels.error;
  // `useViewQuery` keeps the last view's panels while the next loads; they must not be
  // drawn with the new view's specs, so wait for the active view's own data.
  const ready = panels.data !== undefined && !panels.isPlaceholderData && !detail.isPending;
  const templateRunId = board.data?.rows[0]?.latest_run_id ?? null;

  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">
        <AppLink href={hrefs.overview()}>All projects</AppLink>
        <span className="sep">/</span>
        {project}
        <span className="sep">/</span>
        {task}
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
          {boardMeta(board.data).map((text) => (
            <span key={text}>{text}</span>
          ))}
        </p>
      ) : null}

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
            onClick={() => reeval.run()}
            disabled={reeval.pending}
            title="Re-score every run's saved predictions with the current metric versions"
          >
            Re-evaluate all
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => setLaunching(true)}
            title="Launch runs of this task on any host"
          >
            New run
          </button>
        </span>
      </nav>
      {views.error ? <ErrorBox error={views.error} /> : null}
      {reeval.error ? <ErrorBox error={reeval.error} /> : null}
      {launched ? <LaunchedLine launched={launched} /> : null}

      {viewError ? (
        <ErrorBox error={viewError} />
      ) : ready && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={detail.data?.view.panels} />
      ) : (
        <Loading />
      )}

      {launching ? (
        <NewRun
          project={project}
          task={task}
          templateRunId={templateRunId}
          onClose={() => setLaunching(false)}
          onLaunched={(records, host) => {
            setLaunching(false);
            setLaunched({ host, records });
          }}
        />
      ) : null}
    </div>
  );
}
