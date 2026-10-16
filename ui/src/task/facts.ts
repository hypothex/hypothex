/** Pure helpers of the task page: the tab named by `?tab=`, the facts line, the not-found rule. */
import { ApiError } from "../api/client";
import type { Leaderboard, TaskRun, TaskRuns } from "../api/models";
import { keyLabel, latestRun } from "./useRunSelection";

export type TaskTab = { kind: "charts" | "runs" | "sweeps" | "examples" } | { kind: "view"; name: string };

const PLAIN: ReadonlySet<string> = new Set(["runs", "sweeps", "examples"]);

/** `?tab=runs|sweeps|examples|view:<name>`; a legacy `?view=<name>` (not `overview`) opens that view. */
export function parseTab(params: URLSearchParams): TaskTab {
  const tab = params.get("tab") ?? "";
  if (tab.startsWith("view:") && tab.length > 5) return { kind: "view", name: tab.slice(5) };
  if (PLAIN.has(tab)) return { kind: tab as "runs" | "sweeps" | "examples" };
  const legacy = params.get("view");
  if (tab === "" && legacy && legacy !== "overview") return { kind: "view", name: legacy };
  return { kind: "charts" };
}

/** The `?tab=` value of a tab; null for Charts (the default). */
export function tabParam(tab: TaskTab): string | null {
  if (tab.kind === "charts") return null;
  return tab.kind === "view" ? `view:${tab.name}` : tab.kind;
}

export function sameTab(a: TaskTab, b: TaskTab): boolean {
  return tabParam(a) === tabParam(b);
}

export interface TaskFacts {
  primary: string;
  direction: "↑" | "↓";
  /** The best config's mean, its best-scored run (else latest) and its name. */
  best: { value: number; runId: string; name: string } | null;
  runs: number;
  configs: number;
  running: number;
  queued: number;
}

export function taskFacts(data: TaskRuns): TaskFacts {
  const best = data.groups.find((g) => g.is_best && g.primary !== null);
  const members = best ? data.runs.filter((r) => best.run_ids.includes(r.run_id)) : [];
  const sign = data.higher_is_better ? 1 : -1;
  const top =
    members
      .filter((r) => r.primary !== null)
      .reduce<TaskRun | undefined>(
        (a, r) => (a === undefined || sign * ((r.primary as number) - (a.primary as number)) > 0 ? r : a),
        undefined,
      ) ?? latestRun(members);
  return {
    primary: keyLabel(data.primary),
    direction: data.higher_is_better ? "↑" : "↓",
    best: best?.primary && top ? { value: best.primary.mean, runId: top.run_id, name: best.name } : null,
    runs: data.runs.length,
    configs: data.groups.length,
    running: data.runs.filter((r) => r.status === "running").length,
    queued: data.runs.filter((r) => r.status === "queued").length,
  };
}

/** Leaderboard backlog shown in the facts line: runs that need re-evaluation, unscored runs. */
export function boardWarnings(board: Leaderboard): string[] {
  const out: string[] = [];
  if (board.needs_reeval.length > 0) out.push(`${board.needs_reeval.length} need re-eval`);
  if (board.unscored.length > 0) out.push(`${board.unscored.length} unscored`);
  return out;
}

/** `accuracy v1, macro_f1 v1`: the primary fact's tooltip. */
export function metricVersions(board: Leaderboard): string {
  return Object.entries(board.metric_versions)
    .map(([metric, version]) => `${metric} ${version}`)
    .join(", ");
}

/** A 404 (unknown project), or the server's 400 `ConfigError` for an unknown task in a known project. */
export function isGone(e: Error | null): boolean {
  return (
    e instanceof ApiError &&
    (e.status === 404 || (e.status === 400 && e.type === "ConfigError" && /^unknown task\b/.test(e.message)))
  );
}

/** The first not-found among the task's own reads. */
export function notFound(...errors: (Error | null)[]): Error | null {
  return errors.find(isGone) ?? null;
}
