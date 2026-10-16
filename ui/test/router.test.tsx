import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";

import { parseSearch, stringifySearch } from "../src/router";
import { mockRoutes } from "./api/fetch-mock";
import { makeSummary } from "./pages/sweepFixtures";
import { renderApp } from "./render-app";

const realFetch = globalThis.fetch;
beforeEach(() => {
  mockRoutes({});
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

type AppRouter = ReturnType<typeof renderApp>["router"];
/** TanStack's union of route ids (`"/" | "/t/$project/$task" | ...`); a plain string fails TS2769. */
type RouteId = AppRouter["state"]["matches"][number]["routeId"];
const leaf = (router: AppRouter) => router.state.matches.at(-1);
const settled = (router: AppRouter, routeId: RouteId) =>
  waitFor(() => expect(leaf(router)?.routeId).toBe(routeId));

describe("routes", () => {
  test("/ is Home", async () => {
    const { router } = renderApp("/");
    await settled(router, "/");
  });

  test("/t/:project/:task reads ?view", async () => {
    const { router } = renderApp("/t/toy/acc?view=route");
    await settled(router, "/t/$project/$task");
    expect(leaf(router)?.params).toEqual({ project: "toy", task: "acc" });
    expect(leaf(router)?.search).toEqual({ view: "route" });
  });

  test("/t/:project/:task/edit/new is the view editor", async () => {
    const { router } = renderApp("/t/toy/acc/edit/new");
    await settled(router, "/t/$project/$task/edit/$view");
    expect(leaf(router)?.params).toMatchObject({ view: "new" });
  });

  test("/r/:runId decodes the id", async () => {
    const { router } = renderApp("/r/20260927-a%2Fb");
    await settled(router, "/r/$runId");
    expect(leaf(router)?.params).toEqual({ runId: "20260927-a/b" });
  });

  test("/x/:a/:b reads ?metric", async () => {
    const { router } = renderApp("/x/r1/r2?metric=accuracy%40v1");
    await settled(router, "/x/$a/$b");
    expect(leaf(router)?.params).toEqual({ a: "r1", b: "r2" });
    expect(leaf(router)?.search).toEqual({ metric: "accuracy@v1" });
  });

  test("/s/:project/:id redirects to the task's Sweeps tab", async () => {
    mockRoutes({ "/api/v1/sweeps/rxn/s-7f3a": makeSummary() });
    const { router } = renderApp("/s/rxn/s-7f3a");
    await waitFor(() => expect(router.state.location.pathname).toBe("/t/rxn/fwd"));
    expect(router.state.location.search).toEqual({ tab: "sweeps", sweep: "s-7f3a" });
  });

  test("/s/:project/:id of a sweep without a task shows the sweep in place", async () => {
    mockRoutes({ "/api/v1/sweeps/rxn/s-7f3a": makeSummary({}, { task: null }) });
    const { router } = renderApp("/s/rxn/s-7f3a");
    expect(await screen.findByRole("heading", { level: 2, name: "s-7f3a" })).toBeTruthy();
    expect(leaf(router)?.routeId).toBe("/s/$project/$id");
    expect(router.state.location.pathname).toBe("/s/rxn/s-7f3a");
  });

  test("a numeric-looking ?view stays a string (no JSON parsing)", async () => {
    const { router } = renderApp("/t/toy/acc?view=2024");
    await settled(router, "/t/$project/$task");
    expect(leaf(router)?.search).toEqual({ view: "2024" });
  });

  test("/r/:runId keeps ?log and ?example for the run page", async () => {
    const { router } = renderApp("/r/r1?log=stderr&example=T-014");
    await settled(router, "/r/$runId");
    expect(leaf(router)?.search).toEqual({ log: "stderr", example: "T-014" });
  });

  test("/r/:runId keeps a numeric ?example id as a string", async () => {
    const { router } = renderApp("/r/r1?example=42");
    await settled(router, "/r/$runId");
    expect(leaf(router)?.search).toEqual({ log: undefined, example: "42" });
  });

  test("/t/:project/:task keeps the v5 workspace keys, all as strings", async () => {
    const { router } = renderApp(
      "/t/toy/acc?tab=charts&filter=lr%3D3e-4&group=run&sort=top1%3Adesc&hide=g1%2Cg2&sup=0&col=top1%2Ffinal&sweep=s-7f3a",
    );
    await settled(router, "/t/$project/$task");
    expect(leaf(router)?.search).toEqual({
      tab: "charts",
      filter: "lr=3e-4",
      group: "run",
      sort: "top1:desc",
      hide: "g1,g2",
      sup: "0",
      col: "top1/final",
      sweep: "s-7f3a",
    });
  });

  test("validateSearch drops empty v5 keys on the task and run routes", async () => {
    const { cleanup } = await import("@testing-library/react");
    const task = renderApp("/t/toy/acc?tab=&filter=&group=&sort=&hide=&sup=&col=&sweep=&view=");
    await settled(task.router, "/t/$project/$task");
    expect(Object.values(leaf(task.router)?.search ?? {}).filter((v) => v !== undefined)).toEqual([]);
    cleanup();
    const run = renderApp("/r/r1?tab=&log=&example=");
    await settled(run.router, "/r/$runId");
    expect(Object.values(leaf(run.router)?.search ?? {}).filter((v) => v !== undefined)).toEqual([]);
  });

  test("/r/:runId reads ?tab", async () => {
    const { router } = renderApp("/r/r1?tab=logs");
    await settled(router, "/r/$runId");
    expect(leaf(router)?.search).toEqual({ tab: "logs" });
  });

  test("/r/:runId reads ?tab with ?log and ?example", async () => {
    const { router } = renderApp("/r/r1?tab=logs&log=stderr");
    await settled(router, "/r/$runId");
    expect(leaf(router)?.search).toEqual({ tab: "logs", log: "stderr" });
  });

  test("/r/:runId renders the v5 run page", async () => {
    const { router } = renderApp("/r/r1?tab=logs");
    await settled(router, "/r/$runId");
    await waitFor(() => expect(document.querySelector(".run-page")).not.toBeNull());
  });

  test("/hosts and /queue are their own pages", async () => {
    const { cleanup } = await import("@testing-library/react");
    for (const [path, name] of [
      ["/hosts", "Hosts"],
      ["/queue", "Queue"],
    ] as const) {
      const { router } = renderApp(path);
      await settled(router, path);
      expect(leaf(router)?.routeId).toBe(path);
      expect(await screen.findByRole("heading", { level: 1, name })).toBeTruthy();
      expect(document.querySelector(".hosts-page")).not.toBeNull();
      cleanup();
    }
  });

  test("an unknown path shows Not found with a way home", async () => {
    renderApp("/nope/at/all");
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Not found");
    expect(screen.getAllByRole("link", { name: "Home" }).length).toBeGreaterThan(0);
  });
});

describe("search serialization", () => {
  test("parseSearch keeps every value a string; stringifySearch matches URLSearchParams", () => {
    expect(parseSearch("?example=42&view=2024&metric=accuracy%40v1&flag=true")).toEqual({
      example: "42",
      view: "2024",
      metric: "accuracy@v1",
      flag: "true",
    });
    expect(parseSearch("")).toEqual({});
    expect(stringifySearch({ example: "42", log: undefined, metric: "solved@v2" })).toBe(
      "?example=42&metric=solved%40v2",
    );
    expect(stringifySearch({ view: undefined })).toBe("");
    expect(stringifySearch({ n: 3 })).toBe("?n=3");
  });
});
