/**
 * TanStack Query keys, hooks and mutations over the API client.
 *
 * Keys are hierarchical so one prefix invalidates a family: `["run"]` covers every
 * per-run query, `["views", "query"]` every panel query, `["sweeps", project]` every sweep
 * query of a project. `RUN_EVENT_INVALIDATES` is the list the live event stream invalidates
 * on any `run.*` event; `REMOTE_RUN_INVALIDATES` on `mirror.run_updated`;
 * `HOST_EVENT_INVALIDATES` on `host.*`.
 */
import {
  QueryClient,
  type QueryKey,
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ApiError, api } from "./client";
import type * as M from "./models";

export const queryKeys = {
  overview: (since?: string) => ["overview", since ?? null] as const,
  projects: () => ["projects"] as const,
  tasks: (project?: string) => ["tasks", project ?? null] as const,
  task: (project: string, task: string) => ["task", project, task] as const,
  leaderboard: (project: string, task: string, metrics: readonly string[] = []) =>
    ["leaderboard", project, task, [...metrics]] as const,
  taskKind: (project: string, task: string) => ["taskKind", project, task] as const,
  runs: (query: M.RunsQuery = {}) => ["runs", query] as const,
  run: (runId: string) => ["run", runId] as const,
  runLogs: (runId: string, stream: M.LogStream) => ["run", runId, "logs", stream] as const,
  runPredictions: (runId: string, query: M.PredictionsQuery = {}) =>
    ["run", runId, "predictions", query] as const,
  runTraces: (runId: string) => ["run", runId, "traces"] as const,
  runTrace: (runId: string, exampleId: string) => ["run", runId, "traces", exampleId] as const,
  compareExamples: (a: string, b: string, metric: string, field?: string) =>
    ["compareExamples", a, b, metric, field ?? null] as const,
  views: (project: string, task: string) => ["views", "list", project, task] as const,
  view: (project: string, task: string, name: string) => ["views", "doc", project, task, name] as const,
  viewQuery: (project: string, task: string, body: M.ViewQueryBody) =>
    ["views", "query", project, task, body] as const,
  hosts: () => ["hosts"] as const,
  sweep: (project: string, sweepId: string) => ["sweeps", project, "detail", sweepId] as const,
  projectSweeps: (project: string) => ["sweeps", project, "list"] as const,
  allRuns: (query: Omit<M.RunsQuery, "limit">) => ["runs", "all", query] as const,
};

/**
 * Key families a `run.*` event or a run action can change (contract section 4: runs,
 * leaderboard, overview, views/query; plus the task summary, run detail, example
 * comparisons and sweeps that read the same runs). View lists, view documents and `/kind`
 * are never in this list, so an open editor is not reloaded under the user. The hosts list
 * is not either: a hub run does not change a remote host.
 */
export const RUN_EVENT_INVALIDATES: readonly QueryKey[] = [
  ["overview"],
  ["tasks"],
  ["task"],
  ["runs"],
  ["run"],
  ["leaderboard"],
  ["views", "query"],
  ["compareExamples"],
  ["sweeps"],
];

/**
 * Families a remote run change can touch: a `mirror.run_updated` event, a launch on a host,
 * or a sweep action. The run families plus the hosts list (queue length, GPUs, cost today).
 */
export const REMOTE_RUN_INVALIDATES: readonly QueryKey[] = [...RUN_EVENT_INVALIDATES, ["hosts"]];

/**
 * Families a `host.*` event (or a connect/disconnect) can change (phase 2 contract 4): the
 * hosts list, and everything that shows a host's state (overview, run lists, run pages with
 * `host_state`, sweeps). Scores do not change, so leaderboards and panels are left alone.
 */
export const HOST_EVENT_INVALIDATES: readonly QueryKey[] = [
  ["hosts"],
  ["overview"],
  ["runs"],
  ["run"],
  ["sweeps"],
];

/** The hosts list refetches this often: GPU use changes every 10 s with no event (spec 8A.7). */
export const HOSTS_REFETCH_MS = 10_000;

/**
 * Keep a stale host's last known GPUs and queue length.
 *
 * The hub asks a host for its GPUs and queue only while the host is `connected`; for every
 * other state its row has `gpus: []` and `queue: 0`. The Hosts panel and the Launch dialog
 * draw a stale host's last known cells greyed, so a row that is `stale`, has no GPUs of its
 * own, and serves the same environment as in `prev` takes `prev`'s GPUs and queue. Rows in
 * any other state are kept as the hub sent them.
 */
export function keepLastKnown(prev: readonly M.HostRow[] | undefined, next: M.HostRow[]): M.HostRow[] {
  if (prev === undefined) return next;
  const before = new Map(prev.map((row) => [row.name, row]));
  return next.map((row) => {
    const old = before.get(row.name);
    if (old === undefined || row.state.state !== "stale" || row.gpus.length > 0) return row;
    if (old.state.environment_id !== row.state.environment_id) return row;
    return { ...row, gpus: old.gpus, queue: old.queue };
  });
}

/**
 * Each QueryClient's last row with data, by host name: the last `connected` row, or a stale
 * row that already carries one. A host that drops goes `connected` -> `connecting` (and
 * `bootstrapping` on SSH retries) -> `stale`; those middle rows have no GPUs, so the cached
 * list alone would lose the cells before the host turns stale.
 */
const lastKnownRows = new WeakMap<QueryClient, Map<string, M.HostRow>>();

/** Store every row of `rows` that has data (connected, or GPUs carried) in `known`. */
function rememberRows(known: Map<string, M.HostRow>, rows: readonly M.HostRow[]): Map<string, M.HostRow> {
  for (const row of rows) {
    if (row.state.state === "connected" || row.gpus.length > 0) known.set(row.name, row);
  }
  return known;
}

/**
 * `GET /api/v1/hosts` through `keepLastKnown` against the last row with data of each host
 * (seeded from the cached `["hosts"]` list), so a stale host gets the cells it had while
 * connected even when `connecting` or `bootstrapping` polls came between.
 */
export async function fetchHosts(qc: QueryClient, signal?: AbortSignal): Promise<M.HostRow[]> {
  const rows = await api.hosts(signal);
  const known =
    lastKnownRows.get(qc) ?? rememberRows(new Map(), qc.getQueryData<M.HostRow[]>(queryKeys.hosts()) ?? []);
  const out = keepLastKnown([...known.values()], rows);
  lastKnownRows.set(qc, rememberRows(known, out));
  return out;
}

/**
 * The newest event sequence of the server's log: the hub's own row of `GET /api/v1/hosts`
 * (`kind: "local"`, `state.last_sequence`). A new tab subscribes to live events after it
 * instead of replaying the whole log (the page fetches every query anyway). The rows are
 * stored as the hosts query, so a Hosts panel on the same page reuses them.
 *
 * Returns null when the request fails or the row has no valid sequence; the caller then
 * replays from 0.
 *
 * Examples
 * --------
 * >>> await fetchLastSequence(qc)
 * 1022
 */
export async function fetchLastSequence(qc: QueryClient): Promise<number | null> {
  try {
    const rows = await qc.fetchQuery({
      queryKey: queryKeys.hosts(),
      queryFn: ({ signal }) => fetchHosts(qc, signal),
      // always fresh: a cached head from before a store switch could skip new events
      staleTime: 0,
      retry: false,
    });
    const last = rows.find((row) => row.kind === "local")?.state?.last_sequence;
    return typeof last === "number" && Number.isSafeInteger(last) && last >= 0 ? last : null;
  } catch {
    return null;
  }
}

/** Retry transient failures twice; never retry a 4xx (the answer will not change). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

/** The app's QueryClient: 5 s stale time, no refetch on focus (the event stream keeps data fresh). */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: shouldRetry },
      mutations: { retry: false },
    },
  });
}

// reads ------------------------------------------------------------------------------------
/** Options a page may set on a read hook. */
export interface ReadOptions {
  /** False keeps the query idle (for example until the run that names its task loads). */
  enabled?: boolean;
  /** Show the last result while a new key loads (pagination). */
  keepPrevious?: boolean;
}

const readOptions = ({ enabled = true, keepPrevious = false }: ReadOptions) => ({
  enabled,
  placeholderData: keepPrevious ? keepPreviousData : undefined,
});

export const useOverview = (since?: string) =>
  useQuery({ queryKey: queryKeys.overview(since), queryFn: ({ signal }) => api.overview(since, signal) });

export const useProjects = () =>
  useQuery({ queryKey: queryKeys.projects(), queryFn: ({ signal }) => api.projects(signal) });

export const useTasks = (project?: string) =>
  useQuery({ queryKey: queryKeys.tasks(project), queryFn: ({ signal }) => api.tasks(project, signal) });

export const useTask = (project: string, task: string, opts: ReadOptions = {}) =>
  useQuery({
    queryKey: queryKeys.task(project, task),
    queryFn: ({ signal }) => api.task(project, task, signal),
    ...readOptions(opts),
  });

export const useLeaderboard = (
  project: string,
  task: string,
  metrics: readonly string[] = [],
  opts: ReadOptions = {},
) =>
  useQuery({
    queryKey: queryKeys.leaderboard(project, task, metrics),
    queryFn: ({ signal }) => api.leaderboard(project, task, metrics, signal),
    ...readOptions(opts),
  });

export const useTaskKind = (project: string, task: string, opts: ReadOptions = {}) =>
  useQuery({
    queryKey: queryKeys.taskKind(project, task),
    queryFn: ({ signal }) => api.taskKind(project, task, signal),
    ...readOptions(opts),
  });

export const useRuns = (query: M.RunsQuery = {}) =>
  useQuery({ queryKey: queryKeys.runs(query), queryFn: ({ signal }) => api.runs(query, signal) });

export const useRun = (runId: string) =>
  useQuery({ queryKey: queryKeys.run(runId), queryFn: ({ signal }) => api.run(runId, signal) });

export const useRunLogs = (runId: string, stream: M.LogStream = "stdout") =>
  useQuery({
    queryKey: queryKeys.runLogs(runId, stream),
    queryFn: ({ signal }) => api.runLogs(runId, stream, undefined, signal),
  });

export const useRunPredictions = (runId: string, query: M.PredictionsQuery = {}, opts: ReadOptions = {}) =>
  useQuery({
    queryKey: queryKeys.runPredictions(runId, query),
    queryFn: ({ signal }) => api.runPredictions(runId, query, signal),
    ...readOptions(opts),
  });

export const useRunTraces = (runId: string, enabled = true) =>
  useQuery({
    queryKey: queryKeys.runTraces(runId),
    queryFn: ({ signal }) => api.runTraces(runId, signal),
    enabled,
  });

/** One trace; idle until `exampleId` is set. */
export const useRunTrace = (runId: string, exampleId: string | null) =>
  useQuery({
    queryKey: queryKeys.runTrace(runId, exampleId ?? ""),
    queryFn: ({ signal }) => api.runTrace(runId, exampleId ?? "", signal),
    enabled: exampleId !== null,
  });

export const useCompareExamples = (
  a: string,
  b: string,
  metric: string,
  field?: string,
  opts: ReadOptions = {},
) =>
  useQuery({
    queryKey: queryKeys.compareExamples(a, b, metric, field),
    queryFn: ({ signal }) => api.compareExamples(a, b, metric, field, signal),
    ...readOptions(opts),
  });

export const useViews = (project: string, task: string) =>
  useQuery({ queryKey: queryKeys.views(project, task), queryFn: ({ signal }) => api.views(project, task, signal) });

/** One view document; idle while `name` is null (the editor's "new" view). */
export const useView = (project: string, task: string, name: string | null) =>
  useQuery({
    queryKey: queryKeys.view(project, task, name ?? ""),
    queryFn: ({ signal }) => api.view(project, task, name ?? "", signal),
    enabled: name !== null,
  });

/** Panel data for a view, a named view, or one panel; keeps the last result while refetching. */
export const useViewQuery = (project: string, task: string, body: M.ViewQueryBody | null) =>
  useQuery({
    queryKey: queryKeys.viewQuery(project, task, body ?? {}),
    queryFn: ({ signal }) => api.queryView(project, task, body ?? {}, signal),
    enabled: body !== null,
    placeholderData: keepPreviousData,
  });

/**
 * Every host (the hub's `local` row first) with its state, GPUs, queue and cost today; polls
 * every `refetchMs`; a stale host keeps its last known GPUs and queue (`keepLastKnown`).
 * `enabled: false` keeps it idle (the run page of a hub run).
 */
export function useHosts(refetchMs: number = HOSTS_REFETCH_MS, enabled = true) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: queryKeys.hosts(),
    queryFn: ({ signal }) => fetchHosts(qc, signal),
    refetchInterval: refetchMs,
    enabled,
  });
}

export const useSweep = (project: string, sweepId: string) =>
  useQuery({
    queryKey: queryKeys.sweep(project, sweepId),
    queryFn: ({ signal }) => api.sweep(project, sweepId, signal),
  });

export const useProjectSweeps = (project: string) =>
  useQuery({
    queryKey: queryKeys.projectSweeps(project),
    queryFn: ({ signal }) => api.projectSweeps(project, signal),
  });

/** First `limit` of `fetchAllRuns`; each next request asks for 4× as many. */
export const ALL_RUNS_FIRST = 1000;
/** `fetchAllRuns` stops growing here and marks the list cut. */
export const ALL_RUNS_MAX = 64_000;

/** Every run a query matches, and whether the list is whole. */
export interface AllRuns {
  runs: M.RunRecord[];
  /** False only when more than `ALL_RUNS_MAX` runs match. */
  complete: boolean;
}

/**
 * Keyset cursor of `GET /api/v1/runs`: only runs after `(created_at, run_id)` in the
 * newest-first order, i.e. the runs below the last run of the previous page.
 */
export interface RunsCursor {
  before_created_at: string;
  before_run_id: string;
}

/** The cursor after `run`, or null when the run has no `created_at` to page from. */
function cursorAfter(run: M.RunRecord | undefined): RunsCursor | null {
  const created = run?.created_at as unknown;
  return run && typeof created === "string" && created !== ""
    ? { before_created_at: created, before_run_id: run.run_id }
    : null;
}

/**
 * Every run that matches `query`, not only the newest page.
 *
 * Pages by keyset: the next request asks for the runs after the last run so far
 * (`before_created_at`, `before_run_id`), 4× more each time (1,000, 4,000, ...), so no run
 * is read twice. A server that ignores the cursor sends the newest runs again; then the
 * runs overlap the ones so far, and the request is read as the older paging by a growing
 * `limit` (the same requests as before). A host queue or a 1,000-run sweep never loses
 * its oldest runs (the queue head) to the page size either way.
 *
 * Examples
 * --------
 * >>> const { runs, complete } = await fetchAllRuns({ tag: "sweep:ab12cd34:s-7f3a" });
 */
export async function fetchAllRuns(query: Omit<M.RunsQuery, "limit">, signal?: AbortSignal): Promise<AllRuns> {
  let limit = ALL_RUNS_FIRST;
  let runs = await api.runs({ ...query, limit }, signal);
  let full = runs.length >= limit;
  let keyset = true; // until the server shows it ignores the cursor
  while (full) {
    if (keyset ? runs.length >= ALL_RUNS_MAX : limit >= ALL_RUNS_MAX) return { runs, complete: false };
    limit *= 4;
    const cursor = keyset ? cursorAfter(runs.at(-1)) : null;
    // the first keyset page asks for 4,000 like the growing limit, so either reading holds
    const size = cursor ? Math.min(limit, ALL_RUNS_MAX - runs.length) : limit;
    const params: M.RunsQuery & Partial<RunsCursor> = { ...query, limit: size, ...cursor };
    const page = await api.runs(params, signal);
    const seen = new Set(runs.map((r) => r.run_id));
    if (cursor && !page.some((r) => seen.has(r.run_id))) {
      runs = runs.concat(page);
    } else {
      keyset = false; // `page` is the newest `size` runs
      runs = page;
    }
    full = page.length >= size;
  }
  return { runs, complete: true };
}

/** `fetchAllRuns` as a query under `["runs"]`, so every run event refreshes it. */
export const useAllRuns = (query: Omit<M.RunsQuery, "limit">, enabled = true) =>
  useQuery({
    queryKey: queryKeys.allRuns(query),
    queryFn: ({ signal }) => fetchAllRuns(query, signal),
    enabled,
  });

// writes -----------------------------------------------------------------------------------
export function useSaveView(project: string, task: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, text }: { name: string; text: string }) => api.saveView(project, task, name, text),
    // Not awaited: the caller's `onSuccess` (the editor navigates away) must not wait
    // for the editor's own preview query to refetch.
    onSuccess: (_data, { name }) => {
      void qc.invalidateQueries({ queryKey: queryKeys.views(project, task) });
      void qc.invalidateQueries({ queryKey: queryKeys.view(project, task, name) });
      void qc.invalidateQueries({ queryKey: ["views", "query", project, task] });
    },
  });
}
