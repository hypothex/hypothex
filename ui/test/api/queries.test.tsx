import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { ApiError } from "../../src/api/client";
import type { ConnState, HostRow, HostState, RunRecord } from "../../src/api/models";
import {
  ALL_RUNS_FIRST,
  ALL_RUNS_MAX,
  HOST_EVENT_INVALIDATES,
  HOSTS_REFETCH_MS,
  REMOTE_RUN_INVALIDATES,
  RUN_EVENT_INVALIDATES,
  createQueryClient,
  fetchAllRuns,
  fetchHosts,
  keepLastKnown,
  queryKeys,
  shouldRetry,
  useCompareExamples,
  useHosts,
  useLeaderboard,
  useProjectSweeps,
  useRunPredictions,
  useSaveView,
  useSweep,
  useTask,
  useTaskKind,
  useView,
  useViewQuery,
} from "../../src/api/queries";
import { mockApi } from "../pages/helpers";
import { mockRoutes } from "./fetch-mock";
import { HOSTS, SWEEP, SWEEP_LIST } from "./phase2-fixtures";

/** `n` minimal run rows; `fetchAllRuns` only counts them. */
const rows = (n: number): RunRecord[] =>
  Array.from({ length: n }, (_, i) => ({ run_id: `r${i}` }) as unknown as RunRecord);

/** A host row as the hub sends it once the host is not connected: no GPUs, queue 0. */
const gone = (row: HostRow, conn: ConnState, over: Partial<HostState> = {}): HostRow => ({
  ...row,
  gpus: [],
  queue: 0,
  state: { ...row.state, state: conn, since: "2026-10-03T14:31:00Z", ...over },
});

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
      queryKeys.runLogs("r1", "stdout"),
      queryKeys.tasks(),
      queryKeys.task("toy", "acc"),
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.overview(),
      queryKeys.viewQuery("toy", "acc", { name: "overview" }),
      queryKeys.compareExamples("r1", "r2", "accuracy"),
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.projectSweeps("toy"),
    ];
    const miss = [
      queryKeys.views("toy", "acc"),
      queryKeys.view("toy", "acc", "route"),
      queryKeys.projects(),
      queryKeys.hosts(),
    ];
    for (const key of [...hit, ...miss]) qc.setQueryData(key, { seeded: true });
    await Promise.all(RUN_EVENT_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey })));
    expect(hit.map((k) => invalidated(qc, k))).toEqual(hit.map(() => true));
    expect(miss.map((k) => invalidated(qc, k))).toEqual(miss.map(() => false));
  });

  test("phase 2 keys: one hosts list, sweeps under their project", () => {
    expect(queryKeys.hosts()).toEqual(["hosts"]);
    expect(queryKeys.sweep("toy", "s-7f3a")).toEqual(["sweeps", "toy", "detail", "s-7f3a"]);
    expect(queryKeys.projectSweeps("toy")).toEqual(["sweeps", "toy", "list"]);
  });

  test("REMOTE_RUN_INVALIDATES is the run families plus the hosts list", () => {
    expect(REMOTE_RUN_INVALIDATES).toEqual([...RUN_EVENT_INVALIDATES, ["hosts"]]);
  });

  test("keepLastKnown keeps a stale host's last connected GPUs and queue, nothing else", () => {
    const [local, gpu1, mccleary] = HOSTS as [HostRow, HostRow, HostRow, HostRow];
    const next = keepLastKnown([local, gpu1, mccleary], [local, gone(gpu1, "stale"), mccleary]);
    expect(next[1]?.state.state).toBe("stale");
    expect([next[1]?.gpus, next[1]?.queue]).toEqual([gpu1.gpus, 3]);
    expect(next[0]).toBe(local);
    // still stale on the next poll: the same last known cells stay
    expect(keepLastKnown(next, [local, gone(gpu1, "stale"), mccleary])[1]?.gpus).toEqual(gpu1.gpus);
    // other states, no earlier list, or another environment keep the empty row
    expect(keepLastKnown([gpu1], [gone(gpu1, "error")])[0]?.gpus).toEqual([]);
    expect(keepLastKnown(undefined, [gone(gpu1, "stale")])[0]?.gpus).toEqual([]);
    expect(keepLastKnown([gpu1], [gone(gpu1, "stale", { environment_id: "env-new" })])[0]?.queue).toBe(0);
  });

  test("HOST_EVENT_INVALIDATES hits hosts and host-state readers, not scores or views", async () => {
    const { qc } = setup();
    const hit = [
      queryKeys.hosts(),
      queryKeys.overview(),
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r1"),
      queryKeys.sweep("toy", "s-7f3a"),
      queryKeys.projectSweeps("toy"),
    ];
    const miss = [
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.tasks(),
      queryKeys.task("toy", "acc"),
      queryKeys.viewQuery("toy", "acc", { name: "overview" }),
      queryKeys.views("toy", "acc"),
      queryKeys.projects(),
    ];
    for (const key of [...hit, ...miss]) qc.setQueryData(key, { seeded: true });
    await Promise.all(HOST_EVENT_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey })));
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

  test("useHosts polls every 10 s by default", () => {
    expect(HOSTS_REFETCH_MS).toBe(10_000);
  });

  test("useHosts loads the hosts and keeps polling them", async () => {
    const calls = mockRoutes({ "/api/v1/hosts": HOSTS });
    const { wrapper } = setup();
    const { result } = renderHook(() => useHosts(25), { wrapper });
    await waitFor(() =>
      expect(result.current.data?.map((h) => h.name)).toEqual(["local", "gpu1", "mccleary", "dgx"]),
    );
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(3), { timeout: 1_000 });
    expect(new Set(calls.map((c) => c.url))).toEqual(new Set(["/api/v1/hosts"]));
  });

  test("useHosts keeps polling after the hub answers an error", async () => {
    const calls = mockRoutes({ "/api/v1/hosts": null });
    const { wrapper } = setup();
    const { result } = renderHook(() => useHosts(25), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(3), { timeout: 1_000 });
    mockRoutes({ "/api/v1/hosts": HOSTS });
    await waitFor(() => expect(result.current.data?.length).toBe(4), { timeout: 1_000 });
  });

  test("useHosts keeps a stale host's last GPUs and queue between polls", async () => {
    const [local, gpu1] = HOSTS as [HostRow, HostRow];
    mockRoutes({ "/api/v1/hosts": [local, gpu1] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useHosts(25), { wrapper });
    await waitFor(() => expect(result.current.data?.[1]?.gpus.length).toBe(3));
    mockRoutes({ "/api/v1/hosts": [local, gone(gpu1, "stale")] });
    await waitFor(() => expect(result.current.data?.[1]?.state.state).toBe("stale"), { timeout: 1_000 });
    expect([result.current.data?.[1]?.gpus.length, result.current.data?.[1]?.queue]).toEqual([3, 3]);
  });

  test("fetchHosts keeps the last connected GPUs and queue through connecting and bootstrapping", async () => {
    const [local, gpu1] = HOSTS as [HostRow, HostRow];
    const qc = createQueryClient();
    const poll = async (rows: HostRow[]): Promise<HostRow | undefined> => {
      mockRoutes({ "/api/v1/hosts": rows });
      const out = await fetchHosts(qc);
      qc.setQueryData(queryKeys.hosts(), out);
      return out[1];
    };
    expect((await poll([local, gpu1]))?.gpus.length).toBe(3);
    // the hub retries first: these rows have no data and must not draw old cells as live
    const connecting = await poll([local, gone(gpu1, "connecting")]);
    expect([connecting?.gpus, connecting?.queue]).toEqual([[], 0]);
    expect((await poll([local, gone(gpu1, "bootstrapping")]))?.gpus).toEqual([]);
    // then the stale timeout passes: the cells from the last connected poll come back, greyed
    const stale = await poll([local, gone(gpu1, "stale")]);
    expect([stale?.gpus, stale?.queue]).toEqual([gpu1.gpus, 3]);
    expect((await poll([local, gone(gpu1, "stale")]))?.gpus).toEqual(gpu1.gpus);
    // another environment behind the same name: nothing carries over
    expect((await poll([local, gone(gpu1, "stale", { environment_id: "env-new" })]))?.queue).toBe(0);
  });

  test("fetchHosts snapshots are per QueryClient", async () => {
    const [local, gpu1] = HOSTS as [HostRow, HostRow];
    mockRoutes({ "/api/v1/hosts": [local, gpu1] });
    await fetchHosts(createQueryClient());
    mockRoutes({ "/api/v1/hosts": [local, gone(gpu1, "stale")] });
    expect((await fetchHosts(createQueryClient()))[1]?.gpus).toEqual([]);
  });

  test("useHosts keeps a stale host's last GPUs when a connecting poll came between", async () => {
    const [local, gpu1] = HOSTS as [HostRow, HostRow];
    mockRoutes({ "/api/v1/hosts": [local, gpu1] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useHosts(25), { wrapper });
    await waitFor(() => expect(result.current.data?.[1]?.gpus.length).toBe(3));
    mockRoutes({ "/api/v1/hosts": [local, gone(gpu1, "connecting")] });
    await waitFor(() => expect(result.current.data?.[1]?.state.state).toBe("connecting"), { timeout: 1_000 });
    expect(result.current.data?.[1]?.gpus).toEqual([]);
    mockRoutes({ "/api/v1/hosts": [local, gone(gpu1, "stale")] });
    await waitFor(() => expect(result.current.data?.[1]?.state.state).toBe("stale"), { timeout: 1_000 });
    expect([result.current.data?.[1]?.gpus.length, result.current.data?.[1]?.queue]).toEqual([3, 3]);
  });

  test("useSweep loads one sweep under its project key", async () => {
    const calls = mockRoutes({ "/api/v1/sweeps/toy/s-7f3a": SWEEP });
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => useSweep("toy", "s-7f3a"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.headline).toBe("lr 3e-4, beam 10: 0.912 [0.911, 0.913], n = 3");
    expect(qc.getQueryData<typeof SWEEP>(queryKeys.sweep("toy", "s-7f3a"))).toEqual(SWEEP);
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/sweeps/toy/s-7f3a"]);
  });

  test("useProjectSweeps lists a project's sweeps", async () => {
    mockRoutes({ "/api/v1/projects/toy/sweeps": SWEEP_LIST });
    const { wrapper } = setup();
    const { result } = renderHook(() => useProjectSweeps("toy"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((s) => [s.id, s.n_runs])).toEqual([["s-7f3a", 6]]);
  });

  test("fetchAllRuns asks for 4x more while a page comes back full, so no run is cut", async () => {
    const q = "/api/v1/runs?status=queued&environment_id=env-gpu1&limit=";
    // 1,500 queued runs on one host: the first page (1,000) is full, the second is not
    const calls = mockRoutes({ [`${q}1000`]: rows(1000), [`${q}4000`]: rows(1500) });
    const out = await fetchAllRuns({ status: "queued", environment_id: "env-gpu1" });
    expect([out.runs.length, out.complete]).toEqual([1500, true]);
    expect(calls.map((c) => c.url)).toEqual([`${q}1000`, `${q}4000`]);
    expect(queryKeys.allRuns({ status: "queued" })).toEqual(["runs", "all", { status: "queued" }]);
  });

  test("fetchAllRuns stops at ALL_RUNS_MAX and says the list is cut", async () => {
    expect([ALL_RUNS_FIRST, ALL_RUNS_MAX]).toEqual([1000, 64_000]);
    const q = "/api/v1/runs?tag=sweep%3As-1&limit=";
    const calls = mockRoutes({
      [`${q}1000`]: rows(1000),
      [`${q}4000`]: rows(4000),
      [`${q}16000`]: rows(16000),
      [`${q}64000`]: rows(64000),
    });
    const out = await fetchAllRuns({ tag: "sweep:s-1" });
    expect([out.runs.length, out.complete]).toEqual([64000, false]);
    expect(calls).toHaveLength(4);
  });

  test("useView stays idle while name is null", async () => {
    const calls = mockRoutes({});
    const { wrapper } = setup();
    const { result } = renderHook(() => useView("toy", "acc", null), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(calls).toEqual([]);
  });

  test("read hooks stay idle with enabled: false", async () => {
    const calls = mockRoutes({});
    const { wrapper } = setup();
    const { result } = renderHook(
      () => [
        useTask("toy", "acc", { enabled: false }),
        useLeaderboard("toy", "acc", [], { enabled: false }),
        useTaskKind("toy", "acc", { enabled: false }),
        useRunPredictions("r1", { metric: "accuracy" }, { enabled: false }),
        useCompareExamples("r1", "r2", "accuracy", undefined, { enabled: false }),
      ],
      { wrapper },
    );
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.map((q) => q.fetchStatus)).toEqual(["idle", "idle", "idle", "idle", "idle"]);
    expect(calls).toEqual([]);
  });

  test("useRunPredictions keeps the last page only when asked", async () => {
    const page = { run_id: "r1", total: 0, offset: 0, limit: 1, rows: [] };
    mockRoutes({ "/api/v1/runs/r1/predictions": page });
    const { wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ limit, keep }: { limit: number; keep: boolean }) =>
        useRunPredictions("r1", { limit }, { keepPrevious: keep }),
      { wrapper, initialProps: { limit: 1, keep: false } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    rerender({ limit: 2, keep: false });
    expect(result.current.data).toBeUndefined();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    rerender({ limit: 3, keep: true });
    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data).toEqual(page);
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
