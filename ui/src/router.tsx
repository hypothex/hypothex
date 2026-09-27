/**
 * Code-defined routes (contract section 4):
 * `/` Overview, `/t/$project/$task?view=` Task, `/t/$project/$task/edit/$view` View editor
 * (`new` for a new view), `/r/$runId` Run, `/x/$a/$b?metric=` Examples.
 *
 * Each screen replaces its `ScreenPending` component below with the real screen. Screens
 * read params with `getRouteApi("<route id>")` to avoid importing this module.
 */
import {
  Link,
  Outlet,
  type RouterHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { useState } from "react";

import { CommandPalette } from "./shell/CommandPalette";
import { Header } from "./shell/Header";

export interface TaskSearch {
  view?: string;
}

export interface ExamplesSearch {
  metric?: string;
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
    <h1 className="finding" data-testid="screen-pending">
      {name}
    </h1>
  );
}

export function NotFound() {
  return (
    <>
      <h1 className="finding">Not found</h1>
      <p className="metaline">
        <Link to="/">Overview</Link>
      </p>
    </>
  );
}

/** Page frame: header, the routed screen in `<main>`, the command palette. */
export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  return (
    <>
      <Header onFind={() => setPaletteOpen(true)} />
      <main>
        <Outlet />
      </main>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </>
  );
}

export const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });

export const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => <ScreenPending name="Overview" />,
});

export const taskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task",
  validateSearch: (search: Record<string, unknown>): TaskSearch => ({ view: str(search.view) }),
  component: () => <ScreenPending name="Task" />,
});

export const viewEditorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task/edit/$view",
  component: () => <ScreenPending name="View editor" />,
});

export const runRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/r/$runId",
  component: () => <ScreenPending name="Run" />,
});

export const examplesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/x/$a/$b",
  validateSearch: (search: Record<string, unknown>): ExamplesSearch => ({ metric: str(search.metric) }),
  component: () => <ScreenPending name="Examples" />,
});

export const routeTree = rootRoute.addChildren([
  overviewRoute,
  taskRoute,
  viewEditorRoute,
  runRoute,
  examplesRoute,
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
