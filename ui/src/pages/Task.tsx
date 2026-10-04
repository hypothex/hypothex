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
import type { EvalReport, RunRecord } from "../api/models";
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
import { AppLink, hrefs } from "./components/links";
import { PanelGrid } from "./components/PanelGrid";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";
import { paramsText, sweepHref } from "./components/SweepModel";
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

/**
 * What a re-evaluation did, in one line: `0 re-scored · 1 skipped: no predictions`.
 * Skip reasons are counted (`×N`) when there is more than one kind.
 */
export function reevalLine(report: EvalReport): string {
  const skipped = Object.values(report.skipped ?? {});
  const warnings = report.warnings ?? [];
  const out = [`${(report.evaluated ?? []).length} re-scored`];
  if (skipped.length > 0) {
    const reasons = new Map<string, number>();
    for (const why of skipped) reasons.set(why, (reasons.get(why) ?? 0) + 1);
    const many = reasons.size > 1;
    const text = [...reasons].map(([why, n]) => (many ? `${why} ×${n}` : why)).join(", ");
    out.push(`${skipped.length} skipped: ${text}`);
  }
  if (warnings.length > 0) out.push(plural(warnings.length, "warning", "warnings"));
  return out.join(" · ");
}

/** The skipped runs and the warnings of a re-evaluation, one per line, for the tooltip. */
function reevalDetail(report: EvalReport): string | undefined {
  const lines = [
    ...Object.entries(report.skipped ?? {}).map(([id, why]) => `${id}: ${why}`),
    ...(report.warnings ?? []),
  ];
  return lines.length > 0 ? lines.join("\n") : undefined;
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

interface Opened {
  repo: string;
  defaults: LaunchDefaults;
}

/**
 * Loads the repo path, the template run and every run of the task (not only the newest
 * page: an older run may hold a seed), then shows the dialog. What it opened with is kept
 * until the dialog closes: a refetch (each launch invalidates runs) or a failed refetch
 * must not swap the dialog for a spinner or an error and lose the session in it.
 */
function NewRun({ project, task, templateRunId, onClose, onLaunched }: NewRunProps) {
  const detail = useTask(project, task);
  const runs = useAllRuns({ project, task });
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
    if (error) return <ErrorBox error={error} />;
    // a refetch in flight too: a cached list may predate runs started since (by anyone)
    if (
      detail.data === undefined ||
      runs.data === undefined ||
      runs.isFetching ||
      (templateRunId !== null && template.isPending)
    ) {
      return <Loading />;
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

export function TaskPage({ project, task, view }: TaskPageProps) {
  const active = view ? String(view) : "overview";
  const board = useLeaderboard(project, task);
  const views = useViews(project, task);
  const detail = useView(project, task, active);
  const panels = useViewQuery(project, task, { name: active });
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
  const ready = panels.data !== undefined && !panels.isPlaceholderData && !detail.isPending;
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
        <p className="small" role="status" aria-label="Re-evaluate" title={reevalDetail(reevalReport)}>
          {reevalLine(reevalReport)}
        </p>
      ) : null}
      {launched ? <LaunchedLine launched={launched} /> : null}
      <SweepsLine project={project} />

      {viewError ? (
        <ErrorBox error={viewError} />
      ) : ready && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={detail.data?.view.panels} />
      ) : (
        <Loading />
      )}

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
  );
}
