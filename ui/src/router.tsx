/**
 * Code-defined routes (ui-v5 contract): `/` Home, `/t/$project/$task?tab=&filter=&group=
 * &sort=&hide=&sup=&sweep=` Task, `/t/$project/$task/edit/$view` view editor (`new` for a
 * new view), `/r/$runId?tab=` Run, `/x/$a/$b?metric=` Examples, `/s/$project/$id` Sweep,
 * `/hosts`, `/queue`.
 *
 * Old v4 pages stay mounted until their v5 replacement lands; each swap is one `component`
 * line here (see docs/superpowers/plans/2026-10-16-hypothex-ui-v5.md, "How routes switch").
 * Screens read params with `getRouteApi("<route id>")` to avoid importing this module.
 */
import {
  Link,
  type RouterHistory,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
} from "@tanstack/react-router";
import { type ReactElement } from "react";

import { ExamplesPage } from "./pages/Examples";
import { OverviewPage } from "./pages/Overview";
import { RunPage } from "./pages/Run";
import { SweepPage } from "./pages/Sweep";
import { ViewEditor } from "./pages/ViewEditor";
import { AppShell } from "./shell/AppShell";
import { TaskPage } from "./task/TaskPage";

/** The task URL: `tab` is `charts|runs|sweeps|examples|view:<name>`; the rest is the run selection. */
export interface TaskSearch {
  tab?: string;
  /** Legacy view link (v4); the Task page reads it as `tab=view:<name>` (`task/facts` `parseTab`). */
  view?: string;
  sweep?: string;
  filter?: string;
  group?: string;
  sort?: string;
  hide?: string;
  sup?: string;
  col?: string;
}

export interface ExamplesSearch {
  metric?: string;
}

export interface RunSearch {
  tab?: string;
  log?: string;
  example?: string;
}

const str = (v: unknown): string | undefined => (typeof v === "string" && v !== "" ? v : undefined);

/**
 * Search parser for the router: plain `URLSearchParams`, every value a string.
 * TanStack's default JSON-parses values (`?example=42` becomes the number 42), which
 * `str()` would then drop; `hrefs` build every in-app link with `URLSearchParams`, so the
 * router reads search strings the same way. A repeated key keeps its last value.
 */
export function parseSearch(searchStr: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of new URLSearchParams(searchStr)) out[key] = value;
  return out;
}

/** The inverse of `parseSearch`: drops `undefined`/`null`, `String()`s the rest, adds `?`. */
export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const out = params.toString();
  return out ? `?${out}` : "";
}

/** Stand-in until the screen's own component is wired in; shows the screen name. */
export function ScreenPending({ name }: { name: string }) {
  return (
    <div className="pending">
      <h1 className="finding" data-testid="screen-pending">
        {name}
      </h1>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="pending">
      <h1 className="finding">Not found</h1>
      <p className="metaline">
        <Link to="/">Home</Link>
      </p>
    </div>
  );
}

/**
 * `/t/$project/$task`: the Task page; it reads its own search keys (`task/useSearchState`).
 * Screens declare their return type, which keeps the route types free of cycles.
 */
function TaskScreen(): ReactElement {
  const { project, task } = taskRoute.useParams();
  return <TaskPage project={project} task={task} />;
}

/** `/r/$runId?log=&example=`: the Run page. */
function RunScreen(): ReactElement {
  const { runId } = runRoute.useParams();
  const { log, example } = runRoute.useSearch();
  return <RunPage runId={runId} log={log} example={example} />;
}

/** `/x/$a/$b?metric=`: the Examples page. */
function ExamplesScreen(): ReactElement {
  const { a, b } = examplesRoute.useParams();
  const { metric } = examplesRoute.useSearch();
  return <ExamplesPage a={a} b={b} metric={metric} />;
}

/** `/s/$project/$id`: the Sweep page; keyed so a new sweep starts with fresh UI state. */
function SweepScreen(): ReactElement {
  const { project, id } = sweepRoute.useParams();
  return <SweepPage key={`${project}/${id}`} project={project} sweepId={id} />;
}

/** `/t/$project/$task/edit/$view`: the view editor; Save opens the saved view's tab. */
function ViewEditorScreen(): ReactElement {
  const { project, task, view } = viewEditorRoute.useParams();
  const navigate = useNavigate();
  return (
    <ViewEditor
      key={`${project}/${task}/${view}`}
      project={project}
      task={task}
      view={view}
      onSaved={(name) => void navigate({ to: "/t/$project/$task", params: { project, task }, search: { tab: `view:${name}` } })}
    />
  );
}

export const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });

export const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: OverviewPage,
});

export const taskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task",
  validateSearch: (search: Record<string, unknown>): TaskSearch => ({
    tab: str(search.tab),
    view: str(search.view),
    sweep: str(search.sweep),
    filter: str(search.filter),
    group: str(search.group),
    sort: str(search.sort),
    hide: str(search.hide),
    sup: str(search.sup),
    col: str(search.col),
  }),
  component: TaskScreen,
});

export const viewEditorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task/edit/$view",
  component: ViewEditorScreen,
});

export const runRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/r/$runId",
  validateSearch: (search: Record<string, unknown>): RunSearch => ({
    tab: str(search.tab),
    log: str(search.log),
    example: str(search.example),
  }),
  component: RunScreen,
});

export const examplesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/x/$a/$b",
  validateSearch: (search: Record<string, unknown>): ExamplesSearch => ({ metric: str(search.metric) }),
  component: ExamplesScreen,
});

export const sweepRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/s/$project/$id",
  component: SweepScreen,
});

export const hostsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/hosts",
  component: () => <ScreenPending name="Hosts" />,
});

export const queueRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/queue",
  component: () => <ScreenPending name="Queue" />,
});

export const routeTree = rootRoute.addChildren([
  overviewRoute,
  taskRoute,
  viewEditorRoute,
  runRoute,
  examplesRoute,
  sweepRoute,
  hostsRoute,
  queueRoute,
]);

/** Build the router; tests pass a memory history. */
export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    parseSearch,
    stringifySearch,
    defaultPreload: "intent",
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
