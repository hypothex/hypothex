/**
 * TanStack Query keys, hooks and mutations over the API client.
 *
 * Keys are hierarchical so one prefix invalidates a family: `["run"]` covers every
 * per-run query, `["views", "query"]` every panel query. `RUN_EVENT_INVALIDATES` is the
 * list the live event stream invalidates on any `run.*` event.
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
  runMetrics: (runId: string) => ["run", runId, "metrics"] as const,
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
export const useOverview = (since?: string) =>
  useQuery({ queryKey: queryKeys.overview(since), queryFn: ({ signal }) => api.overview(since, signal) });

export const useProjects = () =>
  useQuery({ queryKey: queryKeys.projects(), queryFn: ({ signal }) => api.projects(signal) });

export const useTasks = (project?: string) =>
  useQuery({ queryKey: queryKeys.tasks(project), queryFn: ({ signal }) => api.tasks(project, signal) });

export const useTask = (project: string, task: string) =>
  useQuery({ queryKey: queryKeys.task(project, task), queryFn: ({ signal }) => api.task(project, task, signal) });

export const useLeaderboard = (project: string, task: string, metrics: readonly string[] = []) =>
  useQuery({
    queryKey: queryKeys.leaderboard(project, task, metrics),
    queryFn: ({ signal }) => api.leaderboard(project, task, metrics, signal),
  });

export const useTaskKind = (project: string, task: string) =>
  useQuery({
    queryKey: queryKeys.taskKind(project, task),
    queryFn: ({ signal }) => api.taskKind(project, task, signal),
  });

export const useRuns = (query: M.RunsQuery = {}) =>
  useQuery({ queryKey: queryKeys.runs(query), queryFn: ({ signal }) => api.runs(query, signal) });

export const useRun = (runId: string) =>
  useQuery({ queryKey: queryKeys.run(runId), queryFn: ({ signal }) => api.run(runId, signal) });

export const useRunMetrics = (runId: string) =>
  useQuery({ queryKey: queryKeys.runMetrics(runId), queryFn: ({ signal }) => api.runMetrics(runId, signal) });

export const useRunLogs = (runId: string, stream: M.LogStream = "stdout") =>
  useQuery({
    queryKey: queryKeys.runLogs(runId, stream),
    queryFn: ({ signal }) => api.runLogs(runId, stream, undefined, signal),
  });

export const useRunPredictions = (runId: string, query: M.PredictionsQuery = {}) =>
  useQuery({
    queryKey: queryKeys.runPredictions(runId, query),
    queryFn: ({ signal }) => api.runPredictions(runId, query, signal),
    placeholderData: keepPreviousData,
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

export const useCompareExamples = (a: string, b: string, metric: string, field?: string) =>
  useQuery({
    queryKey: queryKeys.compareExamples(a, b, metric, field),
    queryFn: ({ signal }) => api.compareExamples(a, b, metric, field, signal),
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

export function useDeleteView(project: string, task: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteView(project, task, name),
    onSuccess: async (_data, name) => {
      qc.removeQueries({ queryKey: queryKeys.view(project, task, name) });
      await qc.invalidateQueries({ queryKey: queryKeys.views(project, task) });
    },
  });
}
