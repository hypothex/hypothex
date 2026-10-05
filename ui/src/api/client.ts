/**
 * Typed client for the Hypothex HTTP API (`/api/v1`).
 *
 * Every route string is checked against the generated OpenAPI `paths` (types.ts), so a
 * renamed or removed backend route fails `bun run typecheck` after `bun run gen:types`.
 * Response bodies use the hand-written contract shapes in models.ts.
 */
import { auth } from "./auth";
import type * as M from "./models";
import type { paths } from "./types";

export type * from "./models";

/** Every HTTP route the UI calls. Keys are client names; values must exist in `paths`. */
export const ROUTES = {
  wsTicket: "/api/v1/auth/ws-ticket",
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
  runLogs: "/api/v1/runs/{run_id}/logs",
  runPredictions: "/api/v1/runs/{run_id}/predictions",
  runTraces: "/api/v1/runs/{run_id}/traces",
  runTrace: "/api/v1/runs/{run_id}/traces/{example_id}",
  runRerun: "/api/v1/runs/{run_id}/rerun",
  runReinfer: "/api/v1/runs/{run_id}/reinfer",
  runReeval: "/api/v1/runs/{run_id}/reeval",
  runStop: "/api/v1/runs/{run_id}/stop",
  runNotes: "/api/v1/runs/{run_id}/notes",
  compareExamples: "/api/v1/compare/examples",
  hosts: "/api/v1/hosts",
  hostConnect: "/api/v1/hosts/{host}/connect",
  hostRuns: "/api/v1/hosts/{host}/runs",
  sweep: "/api/v1/sweeps/{project}/{sweep_id}",
  sweepCancelQueued: "/api/v1/sweeps/{project}/{sweep_id}/cancel_queued",
  sweepExtend: "/api/v1/sweeps/{project}/{sweep_id}/extend",
  projectSweeps: "/api/v1/projects/{project}/sweeps",
  runPull: "/api/v1/runs/{run_id}/pull",
  gpus: "/api/v1/gpus",
  queue: "/api/v1/queue",
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
  const credential = auth.capture();
  if (credential.token) headers.Authorization = `Bearer ${credential.token}`;
  const signal = opts.signal ? AbortSignal.any([opts.signal, credential.signal]) : credential.signal;
  const current = (): void => {
    if (signal.aborted || !auth.current(credential.generation)) throw new DOMException("Request superseded", "AbortError");
  };
  current();
  const init: RequestInit = { method, headers, signal };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    current();
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null);
  }
  current();
  if (res.status === 401) {
    auth.lock(credential.generation);
    throw new ApiError(401, "Token required", "AuthError", [], null);
  }
  const text = await res.text();
  current();
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

/** Ticket route checked against the generated OpenAPI schema. */
export const WS_TICKET_ROUTE = ROUTES.wsTicket;
export async function websocketTicket(signal?: AbortSignal): Promise<string | null> {
  const result = await request<{ ticket: string | null; expires_in: number }>("POST", WS_TICKET_ROUTE, { signal, body: {} });
  if (result.ticket === null && result.expires_in === 0) return null;
  if (typeof result.ticket !== "string" || !/^[A-Za-z0-9_-]+$/.test(result.ticket) || result.expires_in !== 30) {
    throw new ApiError(0, "Invalid live stream response", "ProtocolError", [], null);
  }
  return result.ticket;
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
  validateView: (project: string, task: string, text: string, signal?: AbortSignal) =>
    post<M.ViewValidation>(ROUTES.viewValidate, { params: { project, task }, body: { text }, signal }),
  queryView: (project: string, task: string, body: M.ViewQueryBody, signal?: AbortSignal) =>
    post<M.ViewQueryResult>(ROUTES.viewQuery, { params: { project, task }, body, signal }),
  runs: (query: M.RunsQuery = {}, signal?: AbortSignal) =>
    get<M.RunRecord[]>(ROUTES.runs, { query: { ...query }, signal }),
  run: (runId: string, signal?: AbortSignal) =>
    get<M.RunDetail>(ROUTES.run, { params: { run_id: runId }, signal }),
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
  note: (runId: string, text: string, opts?: M.ActionOptions) =>
    post<{ ok: true }>(ROUTES.runNotes, {
      params: { run_id: runId },
      body: { ...action(opts), text, author: opts?.created_by ?? "human" },
    }),
  // phase 2: hosts, launch, sweeps, pull ---------------------------------------------------
  hosts: (signal?: AbortSignal) => get<M.HostRow[]>(ROUTES.hosts, { signal }),
  /** The hub's own GPUs (an env route: the hub is the env server of its own runs). */
  gpus: (signal?: AbortSignal) => get<M.GpuInfo[]>(ROUTES.gpus, { signal }),
  /** The hub's own run queue, in order. */
  queue: (signal?: AbortSignal) => get<M.QueueEntry[]>(ROUTES.queue, { signal }),
  connectHost: (host: string, opts?: M.ActionOptions) =>
    post<M.HostState>(ROUTES.hostConnect, { params: { host }, body: action(opts) }),
  /** Start a run on the hub itself. */
  launch: (body: M.LaunchRequest, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runs, { body: { ...action(opts), ...body } }),
  /** Start or queue a run on a remote host; the hub forwards it and returns the host's record. */
  launchOnHost: (host: string, body: M.HostLaunchRequest, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.hostRuns, { params: { host }, body: { ...action(opts), ...body } }),
  sweep: (project: string, sweepId: string, signal?: AbortSignal) =>
    get<M.SweepSummary>(ROUTES.sweep, { params: { project, sweep_id: sweepId }, signal }),
  projectSweeps: (project: string, signal?: AbortSignal) =>
    get<M.SweepListItem[]>(ROUTES.projectSweeps, { params: { project }, signal }),
  /** Stop the sweep's queued runs (recorded as `killed`); running runs keep going. */
  cancelQueued: (project: string, sweepId: string, opts?: M.ActionOptions) =>
    post<M.SweepSummary>(ROUTES.sweepCancelQueued, {
      params: { project, sweep_id: sweepId },
      body: action(opts),
    }),
  /** Add runs for every parameter combination x each new seed. */
  extendSweep: (project: string, sweepId: string, seeds: readonly number[], opts?: M.ActionOptions) =>
    post<M.SweepSummary>(ROUTES.sweepExtend, {
      params: { project, sweep_id: sweepId },
      body: { ...action(opts), seeds: [...seeds] },
    }),
  /** Copy one remote artifact (a kind such as `checkpoint`, or a run-relative path) to the hub. */
  pull: (runId: string, artifact: string, opts?: M.ActionOptions) =>
    post<M.PullResult>(ROUTES.runPull, { params: { run_id: runId }, body: { ...action(opts), artifact } }),
};
