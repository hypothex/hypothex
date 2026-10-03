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
 * leaderboard, overview, views/query; plus the task summary, run detail and example
 * comparisons that read the same runs). View lists, view documents and `/kind` are never
 * in this list, so an open editor is not reloaded under the user.
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

/** `GET /api/v1/hosts` through `keepLastKnown` against the cached `["hosts"]` list. */
export async function fetchHosts(qc: QueryClient, signal?: AbortSignal): Promise<M.HostRow[]> {
  const rows = await api.hosts(signal);
  return keepLastKnown(qc.getQueryData<M.HostRow[]>(queryKeys.hosts()), rows);
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
 * Every run that matches `query`, not only the newest page.
 *
 * `GET /api/v1/runs` has a `limit` and no offset, so the next page is a bigger limit: start
 * at `ALL_RUNS_FIRST` and ask for 4× more while a page comes back full. A host queue or a
 * 1,000-run sweep then never loses its oldest runs (the queue head) to the page size.
 */
export async function fetchAllRuns(query: Omit<M.RunsQuery, "limit">, signal?: AbortSignal): Promise<AllRuns> {
  for (let limit = ALL_RUNS_FIRST; ; limit *= 4) {
    const runs = await api.runs({ ...query, limit }, signal);
    if (runs.length < limit) return { runs, complete: true };
    if (limit >= ALL_RUNS_MAX) return { runs, complete: false };
  }
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
