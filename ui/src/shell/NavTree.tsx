/**
 * Left navigation (spec section 3): Home, Hosts and Queue with counts, then a project ->
 * task tree with run counts and a spinner on tasks that have running runs.
 */
import { Link, useRouterState } from "@tanstack/react-router";
import { type ReactElement, useMemo } from "react";

import type { RunRecord, TaskSummary } from "../api/models";
import { hasScope, phase3Available } from "../api/scopes";
import { AppLink, hrefs } from "../pages/components/links";
import { useMe, useHosts, useOverview, useTasks } from "../api/queries";
import { Avatar } from "../chrome/Avatar";
import { Icon } from "../chrome/Icon";
import { StatusIcon } from "../chrome/StatusIcon";
import { cx } from "../lib/cx";
import "./shell.css";

export interface NavTask {
  task: string;
  runs: number;
  running: number;
}

export interface NavProject {
  project: string;
  tasks: NavTask[];
}

const key = (project: string, task: string): string => `${project}\u0000${task}`;

/** Projects and their tasks, by name, with run counts and running runs. */
export function buildTree(tasks: readonly TaskSummary[], active: readonly RunRecord[]): NavProject[] {
  const running = new Map<string, number>();
  for (const r of active) {
    if (r.status !== "running" || !r.task) continue;
    const k = key(r.project, r.task);
    running.set(k, (running.get(k) ?? 0) + 1);
  }
  const byProject = new Map<string, NavTask[]>();
  for (const t of tasks) {
    const list = byProject.get(t.project) ?? [];
    list.push({ task: t.name, runs: t.n_runs, running: running.get(key(t.project, t.name)) ?? 0 });
    byProject.set(t.project, list);
  }
  return [...byProject.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([project, list]) => ({ project, tasks: list.sort((a, b) => a.task.localeCompare(b.task)) }));
}

const decode = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

/** True on `/t/<project>/<task>` and its sub-pages. */
export function isTaskPath(pathname: string, project: string, task: string): boolean {
  const parts = pathname.split("/").filter(Boolean).map(decode);
  return parts[0] === "t" && parts[1] === project && parts[2] === task;
}

export function NavTree(): ReactElement {
  const me = useMe();
  const tasks = useTasks();
  const overview = useOverview();
  const hosts = useHosts();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const tree = useMemo(() => buildTree(tasks.data ?? [], overview.data?.running ?? []), [tasks.data, overview.data]);
  const queued = overview.data?.counts.queued;
  const current = (on: boolean) => (on ? ("page" as const) : undefined);
  return (
    <nav className="nav-tree" aria-label="Navigation">
      <div className="nav-sec">
        <Link className={cx("item", pathname === "/" && "on")} to="/" aria-current={current(pathname === "/")}>
          <Icon name="home" />
          Home
        </Link>
        <Link className={cx("item", pathname === "/hosts" && "on")} to="/hosts" aria-current={current(pathname === "/hosts")}>
          <Icon name="hosts" />
          Hosts
          {hosts.data ? <span className="count">{hosts.data.length}</span> : null}
        </Link>
        <Link className={cx("item", pathname === "/queue" && "on")} to="/queue" aria-current={current(pathname === "/queue")}>
          <Icon name="queue" />
          Queue
          {queued !== undefined ? <span className="count">{queued}</span> : null}
        </Link>
        <AppLink className="item" href={hrefs.settings()}>Settings</AppLink>
        {phase3Available(me.data) && hasScope(me.data,"admin") && <AppLink className="item" href={hrefs.storage()}>Storage</AppLink>}
      </div>
      <div className="nav-h">Projects</div>
      <div className="nav-sec grow">
        {tree.length === 0 ? (
          <p className="nav-empty">{tasks.isPending ? "Loading…" : "No projects yet"}</p>
        ) : (
          tree.map((p) => (
            <div key={p.project}>
              <div className="item proj" title={p.project}>
                <Avatar name={p.project} />
                <span className="pn">{p.project}</span>
              </div>
              {phase3Available(me.data) && <AppLink className="item task" href={hrefs.notebook(p.project)}>Notebook</AppLink>}
              {p.tasks.map((t) => {
                const on = isTaskPath(pathname, p.project, t.task);
                return (
                  <Link
                    key={t.task}
                    className={cx("item task", on && "on")}
                    to="/t/$project/$task"
                    params={{ project: p.project, task: t.task }}
                    aria-current={current(on)}
                    title={`${p.project} / ${t.task}`}
                  >
                    {t.running > 0 ? <StatusIcon status="running" iconOnly title={`${t.running} running`} /> : null}
                    <span className="tn">{t.task}</span>
                    <span className="count">{t.runs}</span>
                  </Link>
                );
              })}
            </div>
          ))
        )}
      </div>
    </nav>
  );
}
