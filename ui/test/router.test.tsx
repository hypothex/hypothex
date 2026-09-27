import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";

import { parseSearch, stringifySearch } from "../src/router";
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

  test("a numeric-looking ?view stays a string (no JSON parsing)", async () => {
    const { router } = renderApp("/t/toy/acc?view=2024");
    await settled(router, "/t/$project/$task");
    expect(leaf(router)?.search).toEqual({ view: "2024" });
  });

  test("an unknown path shows Not found with a way home", async () => {
    renderApp("/nope/at/all");
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Not found");
    expect(screen.getAllByRole("link", { name: "Overview" }).length).toBeGreaterThan(0);
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
