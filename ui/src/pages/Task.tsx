/**
 * Task screen (spec 8.3.2): the leaderboard's one-line headline, view tabs (the kind's
 * preset, custom views, `+ view`), and the active view's panels on a 12-column grid.
 */
import { api } from "../api/client";
import { RUN_EVENT_INVALIDATES, useLeaderboard, useView, useViewQuery, useViews } from "../api/queries";
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

  const info = views.data?.find((v) => v.name === active) ?? detail.data?.info;
  const editable = info !== undefined && info.origin !== "preset";
  const viewError = detail.error ?? panels.error;
  const ready = panels.data !== undefined && !detail.isPending;

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
            className="btn primary"
            onClick={() => reeval.run()}
            disabled={reeval.pending}
            title="Re-score every run's saved predictions with the current metric versions"
          >
            Re-evaluate all
          </button>
        </span>
      </nav>
      {views.error ? <ErrorBox error={views.error} /> : null}
      {reeval.error ? <ErrorBox error={reeval.error} /> : null}

      {viewError ? (
        <ErrorBox error={viewError} />
      ) : ready && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={detail.data?.view.panels} />
      ) : (
        <Loading />
      )}
    </div>
  );
}
