import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { ApiError } from "../../src/api/client";
import {
  RUN_EVENT_INVALIDATES,
  createQueryClient,
  queryKeys,
  shouldRetry,
  useLeaderboard,
  useSaveView,
  useView,
  useViewQuery,
} from "../../src/api/queries";
import { mockApi } from "../pages/helpers";
import { mockRoutes } from "./fetch-mock";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function setup(): { qc: QueryClient; wrapper: (p: { children: ReactNode }) => ReactNode } {
  const qc = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, wrapper };
}

const invalidated = (qc: QueryClient, key: readonly unknown[]): boolean | undefined =>
  qc.getQueryState(key)?.isInvalidated;

describe("queryKeys", () => {
  test("families share a prefix", () => {
    expect(queryKeys.leaderboard("toy", "acc", ["accuracy@v2"])).toEqual(["leaderboard", "toy", "acc", ["accuracy@v2"]]);
    expect(queryKeys.runTrace("r1", "ex-3")).toEqual(["run", "r1", "traces", "ex-3"]);
    expect(queryKeys.viewQuery("toy", "acc", { name: "overview" }).slice(0, 2)).toEqual(["views", "query"]);
    expect(queryKeys.views("toy", "acc")).toEqual(["views", "list", "toy", "acc"]);
  });

  test("RUN_EVENT_INVALIDATES hits run data and panel queries but not view documents", async () => {
    const { qc } = setup();
    const hit = [
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r1"),
      queryKeys.runMetrics("r1"),
      queryKeys.tasks(),
      queryKeys.task("toy", "acc"),
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.overview(),
      queryKeys.viewQuery("toy", "acc", { name: "overview" }),
      queryKeys.compareExamples("r1", "r2", "accuracy"),
    ];
    const miss = [queryKeys.views("toy", "acc"), queryKeys.view("toy", "acc", "route"), queryKeys.projects()];
    for (const key of [...hit, ...miss]) qc.setQueryData(key, { seeded: true });
    await Promise.all(RUN_EVENT_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey })));
    expect(hit.map((k) => invalidated(qc, k))).toEqual(hit.map(() => true));
    expect(miss.map((k) => invalidated(qc, k))).toEqual(miss.map(() => false));
  });
});

describe("shouldRetry", () => {
  test("never retries a 4xx, retries other failures twice", () => {
    const notFound = new ApiError(404, "run x not found", "RunNotFoundError", [], null);
    const offline = new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null);
    expect(shouldRetry(0, notFound)).toBe(false);
    expect([shouldRetry(0, offline), shouldRetry(1, offline), shouldRetry(2, offline)]).toEqual([true, true, false]);
  });
});

describe("hooks", () => {
  test("useLeaderboard loads the board", async () => {
    mockRoutes({ "/api/v1/tasks/toy/acc/leaderboard": { task: "acc", headline: "SVM +0.037 over rf, p = 0.15" } });
    const { wrapper } = setup();
    const { result } = renderHook(() => useLeaderboard("toy", "acc"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.headline).toBe("SVM +0.037 over rf, p = 0.15");
  });

  test("useView stays idle while name is null", async () => {
    const calls = mockRoutes({});
    const { wrapper } = setup();
    const { result } = renderHook(() => useView("toy", "acc", null), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(calls).toEqual([]);
  });

  test("useSaveView invalidates the view list, the document and panel queries of that task", async () => {
    mockRoutes({ "/api/v1/tasks/toy/acc/views/route": { info: { name: "route" }, view: { title: "r" } } });
    const { qc, wrapper } = setup();
    const list = queryKeys.views("toy", "acc");
    const doc = queryKeys.view("toy", "acc", "route");
    const panels = queryKeys.viewQuery("toy", "acc", { name: "route" });
    const other = queryKeys.views("toy", "other");
    for (const key of [list, doc, panels, other]) qc.setQueryData(key, []);
    const { result } = renderHook(() => useSaveView("toy", "acc"), { wrapper });
    act(() => result.current.mutate({ name: "route", text: "title: r\n" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect([list, doc, panels, other].map((k) => invalidated(qc, k))).toEqual([true, true, true, false]);
  });

  test("useSaveView succeeds without waiting for the invalidated queries to refetch", async () => {
    let queries = 0;
    mockApi({
      "POST /api/v1/tasks/toy/acc/views/query": () => {
        queries += 1;
        // The first load answers; the refetch after the save never does.
        return queries === 1 ? { panels: [] } : new Promise(() => {});
      },
      "PUT /api/v1/tasks/toy/acc/views/route": { info: { name: "route" }, view: { title: "r" } },
    });
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({ panels: useViewQuery("toy", "acc", { name: "route" }), save: useSaveView("toy", "acc") }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.panels.isSuccess).toBe(true));
    act(() => result.current.save.mutate({ name: "route", text: "title: r\n" }));
    await waitFor(() => expect(queries).toBe(2));
    await waitFor(() => expect(result.current.save.isSuccess).toBe(true));
    expect(result.current.panels.isFetching).toBe(true);
  });
});
