/**
 * Typed client for the Hypothex HTTP API (`/api/v1`).
 *
 * Every route string is checked against the generated OpenAPI `paths` (types.ts), so a
 * renamed or removed backend route fails `bun run typecheck` after `bun run gen:types`.
 * Response bodies use the hand-written contract shapes in models.ts.
 */
import type * as M from "./models";
import type { paths } from "./types";

export type * from "./models";

/** Every HTTP route the UI calls. Keys are client names; values must exist in `paths`. */
export const ROUTES = {
  environment: "/.well-known/hypothex/environment",
  overview: "/api/v1/overview",
  projects: "/api/v1/projects",
  tasks: "/api/v1/tasks",
  task: "/api/v1/tasks/{project}/{task}",
  leaderboard: "/api/v1/tasks/{project}/{task}/leaderboard",
  taskReeval: "/api/v1/tasks/{project}/{task}/reeval",
  taskKind: "/api/v1/tasks/{project}/{task}/kind",
  views: "/api/v1/tasks/{project}/{task}/views",
  view: "/api/v1/tasks/{project}/{task}/views/{name}",
  viewValidate: "/api/v1/tasks/{project}/{task}/views/validate",
  viewQuery: "/api/v1/tasks/{project}/{task}/views/query",
  runs: "/api/v1/runs",
  run: "/api/v1/runs/{run_id}",
  runMetrics: "/api/v1/runs/{run_id}/metrics",
  runLogs: "/api/v1/runs/{run_id}/logs",
  runPredictions: "/api/v1/runs/{run_id}/predictions",
  runTraces: "/api/v1/runs/{run_id}/traces",
  runTrace: "/api/v1/runs/{run_id}/traces/{example_id}",
  runRerun: "/api/v1/runs/{run_id}/rerun",
  runReinfer: "/api/v1/runs/{run_id}/reinfer",
  runReeval: "/api/v1/runs/{run_id}/reeval",
  runStop: "/api/v1/runs/{run_id}/stop",
  runTags: "/api/v1/runs/{run_id}/tags",
  runStar: "/api/v1/runs/{run_id}/star",
  runArchive: "/api/v1/runs/{run_id}/archive",
  runNotes: "/api/v1/runs/{run_id}/notes",
  compareExamples: "/api/v1/compare/examples",
} as const satisfies Record<string, keyof paths>;

export type Route = (typeof ROUTES)[keyof typeof ROUTES];
export type QueryValue = string | number | boolean | readonly string[] | null | undefined;
export type Method = "GET" | "POST" | "PUT" | "DELETE";

export interface RequestOptions {
  params?: Record<string, string>;
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

/** An API failure. `status` 0 means the server could not be reached. */
export class ApiError extends Error {
  readonly status: number;
  readonly type: string;
  readonly issues: M.ValidationIssue[];
  readonly body: unknown;

  constructor(status: number, message: string, type: string, issues: M.ValidationIssue[], body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
    this.issues = issues;
    this.body = body;
  }

  /** Build from a response status and its parsed body (`{error, type}`, `{error, issues}`, or FastAPI `{detail}`). */
  static from(status: number, body: unknown): ApiError {
    if (body !== null && typeof body === "object") {
      const b = body as Record<string, unknown>;
      const issues = Array.isArray(b.issues) ? (b.issues as M.ValidationIssue[]) : [];
      if (typeof b.error === "string") {
        return new ApiError(status, b.error, typeof b.type === "string" ? b.type : "HTTPError", issues, body);
      }
      if (Array.isArray(b.detail) && b.detail.length > 0) {
        const first = b.detail[0] as { msg?: unknown; loc?: unknown };
        const loc = Array.isArray(first.loc) ? first.loc.join(".") : "";
        const msg = typeof first.msg === "string" ? first.msg : "invalid request";
        return new ApiError(status, loc ? `${loc}: ${msg}` : msg, "RequestValidationError", issues, body);
      }
      if (typeof b.detail === "string") return new ApiError(status, b.detail, "HTTPError", issues, body);
    }
    const text = typeof body === "string" && body ? `: ${body.slice(0, 200)}` : "";
    return new ApiError(status, `HTTP ${status}${text}`, "HTTPError", [], body);
  }
}

/**
 * Fill `{name}` placeholders (URL-encoded) and append query parameters.
 *
 * `undefined` and `null` query values are dropped; arrays repeat the key.
 */
export function buildUrl(route: string, params: Record<string, string> = {}, query: Record<string, QueryValue> = {}): string {
  const path = route.replace(/\{(\w+)\}/g, (_match, key: string) => {
    const value = params[key];
    if (value === undefined) throw new Error(`missing path parameter "${key}" for ${route}`);
    return encodeURIComponent(value);
  });
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) for (const item of value) qs.append(key, item);
    else qs.append(key, String(value));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/** Send one request and return the parsed JSON body, or throw `ApiError`. */
export async function request<T>(method: Method, route: Route, opts: RequestOptions = {}): Promise<T> {
  const url = buildUrl(route, opts.params, opts.query);
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, headers, signal: opts.signal };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) throw ApiError.from(res.status, data);
  return data as T;
}

/** WebSocket URL of the live event stream, on the page's own origin. */
export function wsUrl(): string {
  const url = new URL("/api/v1/ws", window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/** A fresh idempotency key for a POST/PUT action. */
export function newCommandId(): string {
  return crypto.randomUUID();
}

function action(opts: M.ActionOptions = {}): { command_id: string; created_by: string } {
  return { command_id: opts.command_id ?? newCommandId(), created_by: opts.created_by ?? "human" };
}

const get = <T>(route: Route, opts: RequestOptions = {}): Promise<T> => request<T>("GET", route, opts);
const post = <T>(route: Route, opts: RequestOptions = {}): Promise<T> => request<T>("POST", route, opts);

export const api = {
  environment: (signal?: AbortSignal) => get<Record<string, unknown>>(ROUTES.environment, { signal }),
  overview: (since?: string, signal?: AbortSignal) =>
    get<M.OverviewSummary>(ROUTES.overview, { query: { since }, signal }),
  projects: (signal?: AbortSignal) => get<M.ProjectInfo[]>(ROUTES.projects, { signal }),
  tasks: (project?: string, signal?: AbortSignal) =>
    get<M.TaskSummary[]>(ROUTES.tasks, { query: { project }, signal }),
  task: (project: string, task: string, signal?: AbortSignal) =>
    get<M.TaskDetail>(ROUTES.task, { params: { project, task }, signal }),
  leaderboard: (project: string, task: string, metrics?: readonly string[], signal?: AbortSignal) =>
    get<M.Leaderboard>(ROUTES.leaderboard, { params: { project, task }, query: { metric: metrics }, signal }),
  taskKind: (project: string, task: string, signal?: AbortSignal) =>
    get<M.TaskKindInfo>(ROUTES.taskKind, { params: { project, task }, signal }),
  views: (project: string, task: string, signal?: AbortSignal) =>
    get<M.ViewInfo[]>(ROUTES.views, { params: { project, task }, signal }),
  view: (project: string, task: string, name: string, signal?: AbortSignal) =>
    get<M.ViewDocument>(ROUTES.view, { params: { project, task, name }, signal }),
  saveView: (project: string, task: string, name: string, text: string, opts: M.ActionOptions = {}) =>
    request<M.SavedView>("PUT", ROUTES.view, {
      params: { project, task, name },
      body: { text, command_id: action(opts).command_id },
    }),
  deleteView: (project: string, task: string, name: string) =>
    request<{ ok: true }>("DELETE", ROUTES.view, { params: { project, task, name } }),
  validateView: (project: string, task: string, text: string, signal?: AbortSignal) =>
    post<M.ViewValidation>(ROUTES.viewValidate, { params: { project, task }, body: { text }, signal }),
  queryView: (project: string, task: string, body: M.ViewQueryBody, signal?: AbortSignal) =>
    post<M.ViewQueryResult>(ROUTES.viewQuery, { params: { project, task }, body, signal }),
  runs: (query: M.RunsQuery = {}, signal?: AbortSignal) =>
    get<M.RunRecord[]>(ROUTES.runs, { query: { ...query }, signal }),
  run: (runId: string, signal?: AbortSignal) =>
    get<M.RunDetail>(ROUTES.run, { params: { run_id: runId }, signal }),
  runMetrics: (runId: string, signal?: AbortSignal) =>
    get<M.MetricPoint[]>(ROUTES.runMetrics, { params: { run_id: runId }, signal }),
  runLogs: (runId: string, stream: M.LogStream = "stdout", offset?: number, signal?: AbortSignal) =>
    get<M.LogChunk>(ROUTES.runLogs, { params: { run_id: runId }, query: { stream, offset }, signal }),
  runPredictions: (runId: string, query: M.PredictionsQuery = {}, signal?: AbortSignal) =>
    get<M.PredictionPage>(ROUTES.runPredictions, { params: { run_id: runId }, query: { ...query }, signal }),
  runTraces: (runId: string, signal?: AbortSignal) =>
    get<M.TraceSummary[]>(ROUTES.runTraces, { params: { run_id: runId }, signal }),
  runTrace: (runId: string, exampleId: string, signal?: AbortSignal) =>
    get<M.PanelResult>(ROUTES.runTrace, { params: { run_id: runId, example_id: exampleId }, signal }),
  compareExamples: (a: string, b: string, metric: string, field?: string, signal?: AbortSignal) =>
    get<M.ExampleDiff>(ROUTES.compareExamples, { query: { a, b, metric, field }, signal }),
  rerun: (runId: string, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runRerun, { params: { run_id: runId }, body: action(opts) }),
  reinfer: (runId: string, checkpoint?: string, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runReinfer, { params: { run_id: runId }, body: { ...action(opts), checkpoint } }),
  reevalRun: (runId: string, args: { metric?: string; force?: boolean } = {}, opts?: M.ActionOptions) =>
    post<M.EvalReport>(ROUTES.runReeval, { params: { run_id: runId }, body: { ...action(opts), ...args } }),
  reevalTask: (project: string, task: string, args: { metric?: string; force?: boolean } = {}, opts?: M.ActionOptions) =>
    post<M.EvalReport>(ROUTES.taskReeval, { params: { project, task }, body: { ...action(opts), ...args } }),
  stop: (runId: string, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runStop, { params: { run_id: runId }, body: action(opts) }),
  tag: (runId: string, add: string[], remove: string[] = [], opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runTags, { params: { run_id: runId }, body: { ...action(opts), add, remove } }),
  star: (runId: string, on: boolean, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runStar, { params: { run_id: runId }, body: { ...action(opts), on } }),
  archive: (runId: string, on: boolean, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runArchive, { params: { run_id: runId }, body: { ...action(opts), on } }),
  note: (runId: string, text: string, opts?: M.ActionOptions) =>
    post<{ ok: true }>(ROUTES.runNotes, {
      params: { run_id: runId },
      body: { ...action(opts), text, author: opts?.created_by ?? "human" },
    }),
};
