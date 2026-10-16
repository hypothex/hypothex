/**
 * What the run page knows about one run (built once in RunPage, read by every tab and the
 * sidebar), and the pure rules behind it: tabs from the URL, the run's identity colour in
 * its task (principle 1), and which run the Examples page compares it with.
 */
import type { HostRow, RunDetail, RunRecord, TaskGroup, TaskKindInfo, TaskRun, TaskRuns } from "../api/models";
import { colorFor } from "../lib/color";
import type { RunPhase } from "../pages/components/remote";
import { defaultSelection, visibleIdentities } from "../task/useRunSelection";
import type { RunTitle } from "./RunName";

export const LOG_STREAMS = ["stdout", "stderr", "supervisor"] as const;
export type LogStream = (typeof LOG_STREAMS)[number];

/** Accept only the log streams the API serves (the value comes from the URL). */
export function asLogStream(value: unknown): LogStream | null {
  return LOG_STREAMS.find((s) => s === value) ?? null;
}

export const RUN_TABS = ["overview", "charts", "logs", "files", "examples"] as const;
export type RunTab = (typeof RUN_TABS)[number];
export const RUN_TAB_LABELS: Record<RunTab, string> = {
  overview: "Overview",
  charts: "Charts",
  logs: "Logs",
  files: "Files",
  examples: "Examples",
};

export function asRunTab(value: unknown): RunTab | null {
  return RUN_TABS.find((t) => t === value) ?? null;
}

/** The tab to show: `?tab=`, else Logs for an old `?log=` link (failures, Where), else Overview. */
export function shownTab(tab: unknown, log: unknown): RunTab {
  return asRunTab(tab) ?? (asLogStream(log) ? "logs" : "overview");
}

export interface RunIdentity {
  run: TaskRun | null;
  group: TaskGroup | null;
  /** The other runs of the run's config (its seeds), in the task's list order. */
  siblings: TaskRun[];
  /** `var(--cN)` of the run's config in the Task page's default selection; `var(--c0)` otherwise. */
  color: string;
}

export const NO_IDENTITY: RunIdentity = { run: null, group: null, siblings: [], color: "var(--c0)" };

export function runIdentity(data: TaskRuns | null | undefined, runId: string): RunIdentity {
  const run = data?.runs.find((r) => r.run_id === runId) ?? null;
  if (!data || !run) return NO_IDENTITY;
  return {
    run,
    group: data.groups.find((g) => g.group_id === run.group_id) ?? null,
    siblings: data.runs.filter((r) => r.group_id === run.group_id && r.run_id !== runId),
    color: colorFor(run.group_id, visibleIdentities(defaultSelection(data.higher_is_better), data)),
  };
}

export interface ExampleTarget {
  runId: string;
  groupId: string;
  name: string;
  primary: number;
  color: string;
}

/** Other scored configs of the task, best first in the primary's direction, each by its newest run. */
export function exampleTargets(data: TaskRuns | null | undefined, runId: string): ExampleTarget[] {
  const me = data?.runs.find((r) => r.run_id === runId);
  if (!data || !me) return [];
  const visible = visibleIdentities(defaultSelection(data.higher_is_better), data);
  const sign = data.higher_is_better ? -1 : 1;
  return data.groups
    .filter((g) => g.group_id !== me.group_id && g.primary !== null)
    .sort((a, b) => sign * ((a.primary?.mean ?? 0) - (b.primary?.mean ?? 0)))
    .flatMap((g) => {
      const newest = data.runs
        .filter((r) => r.group_id === g.group_id)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
      return newest
        ? [{ runId: newest.run_id, groupId: g.group_id, name: g.name, primary: g.primary?.mean ?? 0, color: colorFor(g.group_id, visible) }]
        : [];
    });
}

/** The header's Compare target: the best other config's newest run. */
export function compareTarget(data: TaskRuns | null | undefined, runId: string): string | null {
  return exampleTargets(data, runId)[0]?.runId ?? null;
}

export interface RunContext {
  runId: string;
  detail: RunDetail;
  record: RunRecord;
  phase: RunPhase;
  /** The hosts row serving a remote run (`runHostRow`); null for a hub run or without the list. */
  host: HostRow | null;
  hostsLoaded: boolean;
  /** The run lives on a remote host (`host_state` set) or on an environment no host serves. */
  remote: boolean;
  now: number;
  lostWhy: string | null;
  hubEnvId: string | null;
  taskRuns: TaskRuns | null;
  identity: RunIdentity;
  title: RunTitle;
  kind: TaskKindInfo | null;
  kindError: unknown;
  inferStage: boolean | undefined;
  /** Examples link for Compare; null: no other config yet; undefined: the run has no task. */
  compareHref: string | null | undefined;
  example: string | undefined;
  log: LogStream | null;
}
