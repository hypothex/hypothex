import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";

import { legacyView, parseSearch, stringifySearch } from "../src/router";
import { mockRoutes } from "./api/fetch-mock";
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
  test("/ is the overview", async () => {
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

  test("/s/:project/:id is the sweep page", async () => {
    const { router } = renderApp("/s/rxn/s-7f3a");
    await settled(router, "/s/$project/$id");
    expect(leaf(router)?.params).toEqual({ project: "rxn", id: "s-7f3a" });
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
      "/t/toy/acc?tab=charts&filter=lr%3D3e-4&group=run&sort=top1%3Adesc&hide=g1%2Cg2&sup=0&sweep=s-7f3a",
    );
    await settled(router, "/t/$project/$task");
    expect(leaf(router)?.search).toEqual({
      tab: "charts",
      filter: "lr=3e-4",
      group: "run",
      sort: "top1:desc",
      hide: "g1,g2",
      sup: "0",
      sweep: "s-7f3a",
    });
  });

  test("validateSearch drops empty v5 keys on the task and run routes", async () => {
    const { cleanup } = await import("@testing-library/react");
    const task = renderApp("/t/toy/acc?tab=&filter=&group=&sort=&hide=&sup=&sweep=&view=");
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

  test("/hosts and /queue are routes", async () => {
    const { cleanup } = await import("@testing-library/react");
    for (const [path, id, name] of [
      ["/hosts", "/hosts", "Hosts"],
      ["/queue", "/queue", "Queue"],
    ] as const) {
      const { router } = renderApp(path);
      await settled(router, id);
      expect(leaf(router)?.routeId).toBe(id);
      expect((await screen.findByTestId("screen-pending")).textContent).toBe(name);
      cleanup();
    }
  });

  test("an unknown path shows Not found with a way home", async () => {
    renderApp("/nope/at/all");
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Not found");
    expect(screen.getAllByRole("link", { name: "Home" }).length).toBeGreaterThan(0);
  });
});

test("every route renders its own screen, not the placeholder", async () => {
  const { cleanup } = await import("@testing-library/react");
  for (const path of ["/", "/t/toy/acc", "/t/toy/acc/edit/new", "/r/r1", "/x/r1/r2?metric=accuracy", "/s/rxn/s-7f3a"]) {
    const { router } = renderApp(path);
    await waitFor(() => expect(router.state.status).toBe("idle"));
    expect([path, screen.queryByTestId("screen-pending")]).toEqual([path, null]);
    cleanup();
  }
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

test("legacyView: ?view, else tab=view:<name>, for the old Task page", () => {
  expect([
    legacyView({ view: "route" }),
    legacyView({ tab: "view:latency" }),
    legacyView({ tab: "charts" }),
    legacyView({ tab: "view:" }),
    legacyView({ view: "a", tab: "view:b" }),
    legacyView({}),
  ]).toEqual(["route", "latency", undefined, undefined, "a", undefined]);
});
