/** Home's numbers and rows (spec 4.1), from `GET /overview` and `GET /hosts`. Pure. */
import type { FailureRow, HostRow, OverviewSummary, RecentRun, RunRecord, RunStatus } from "../api/models";
import { parseTime, primaryMetricName } from "../pages/components/format";
import { fmtMoney } from "../pages/components/HostsPanel";
import { runTitle } from "../run/RunName";

export interface Kpi {
  label: string;
  value: string;
  status?: RunStatus;
  title?: string;
}

const DAY_MS = 86_400_000;

/** Midnight UTC of `now` (the UI shows times in UTC). */
export function utcDayStart(now: number): number {
  return Math.floor(now / DAY_MS) * DAY_MS;
}

/** GPUs of connected hosts held by an hx run or another process, of all their GPUs. */
export function gpusBusy(hosts: readonly HostRow[]): { busy: number; total: number } {
  let busy = 0;
  let total = 0;
  for (const h of hosts) {
    if (h.state.state !== "connected") continue;
    for (const g of h.gpus) {
      total += 1;
      if (g.run_id !== null || g.external) busy += 1;
    }
  }
  return { busy, total };
}

/** The status strip: live projects, running, queued, failed today, lost, GPUs busy, spent today. */
export function statusStrip(summary: OverviewSummary, hosts: readonly HostRow[], now: number): Kpi[] {
  const running = summary.running.filter((r) => r.status === "running");
  const count = (key: string, fallback: number): number => summary.counts[key] ?? fallback;
  const today = utcDayStart(now);
  const gpus = gpusBusy(hosts);
  // the overview's cost today covers every run (hub runs too); the hosts' sum is the fallback
  const usd = summary.cost_today_usd ?? hosts.reduce((a, h) => a + h.cost_today_usd, 0);
  return [
    { label: "projects with live runs", value: String(new Set(running.map((r) => r.project)).size) },
    { label: "running", value: String(count("running", running.length)), status: "running" },
    { label: "queued", value: String(count("queued", summary.running.length - running.length)), status: "queued" },
    // `failures` also holds lost and archived runs; the timeline carries each run's status
    {
      label: "failed today",
      value: String(summary.timeline.filter((t) => t.status === "failed" && !t.archived && parseTime(t.created_at) >= today).length),
      status: "failed",
    },
    { label: "lost", value: String(count("lost", 0)), status: "lost", title: "lost in the last 24 h" },
    { label: "GPUs busy", value: gpus.total > 0 ? `${gpus.busy} / ${gpus.total}` : "—" },
    { label: "spent today", value: fmtMoney(usd) },
  ];
}

/** A store with no run at all (first open of a fresh install). */
export function isEmptyHome(summary: OverviewSummary): boolean {
  return (
    summary.running.length === 0 &&
    summary.failures.length === 0 &&
    (summary.recent ?? summary.timeline).length === 0 &&
    summary.projects.every((p) => p.runs === 0)
  );
}

/** The run view name from the hub, else the record's name or hypothesis clause with the seed. */
export function runLabel(summary: OverviewSummary, record: Pick<RunRecord, "run_id" | "hypothesis" | "seed" | "name">): string {
  return summary.names?.[record.run_id] ?? runTitle(null, record).display;
}

export interface TaskRow {
  project: string;
  task: string;
  kind: string;
  metric: string;
  arrow: "↑" | "↓";
  higherIsBetter: boolean;
  best: number | null;
  unit: string;
  delta: number | null;
  improved: boolean;
  history: number[];
  runs: number;
  running: number;
  queued: number;
}

/** One row per task: primary with direction, best, 7-day Δ, best over time, what runs now. */
export function taskRows(summary: OverviewSummary): TaskRow[] {
  return summary.projects
    .filter((p) => Boolean(p.task))
    .map((p) => {
      const hib = p.higher_is_better ?? true;
      const ago = p.best_7d_ago ?? null;
      const delta = p.best !== null && ago !== null ? p.best - ago : null;
      const active = summary.running.filter((r) => r.project === p.project && r.task === p.task);
      return {
        project: p.project,
        task: p.task,
        kind: p.kind.replace(/_/g, " "),
        metric: primaryMetricName(p.primary ?? "") || "—",
        arrow: hib ? "↑" : "↓",
        higherIsBetter: hib,
        best: p.best,
        unit: p.unit,
        delta,
        improved: delta !== null && (hib ? delta > 0 : delta < 0),
        history: p.best_history ?? [],
        runs: p.runs,
        running: p.running ?? active.filter((r) => r.status === "running").length,
        queued: p.queued ?? active.filter((r) => r.status === "queued").length,
      };
    });
}

/** Failures with the same label and exit code, in first-seen order (rows come newest first). */
export function groupFailures(failures: FailureRow[]): FailureRow[][] {
  const groups = new Map<string, FailureRow[]>();
  for (const f of failures) {
    const key = JSON.stringify([f.label, f.exit_code, f.owner ?? null]);
    const group = groups.get(key);
    if (group) group.push(f);
    else groups.set(key, [f]);
  }
  return [...groups.values()];
}

/** `failed · exit 137`, `lost · host gone`, `finished`. */
export function reasonText(status: RunStatus, exitCode: number | null, reason: string | null): string {
  if (status === "failed") return exitCode !== null ? `failed · exit ${exitCode}` : "failed";
  if (status === "lost") return reason ? `lost · ${reason}` : "lost";
  return status;
}

export interface RecentRow {
  owner?: string | null;
  runId: string;
  at: string;
  name: string;
  project: string;
  task: string | null;
  status: RunStatus;
  reason: string;
  score: number | null;
  deltaBest: number | null;
  by: string;
  hypothesis: string;
  /** stderr path of a failed run (Open stderr, copy). */
  stderr: string | null;
  retried: boolean;
  /** Failures folded into this row (×N). */
  count: number;
}

/** An older hub sends no `recent`: the unarchived, non-queued timeline items (oldest first) instead. */
function fromTimeline(summary: OverviewSummary): RecentRun[] {
  return [...summary.timeline]
    .reverse()
    .filter((t) => t.status !== "queued" && !t.archived)
    .map((t) => ({
      run_id: t.run_id,
      owner:t.owner,
      project: t.project,
      task: t.task,
      name: t.label,
      status: t.status,
      end_reason: null,
      exit_code: null,
      created_at: t.created_at,
      created_by: t.created_by,
      hypothesis: "",
      primary: null,
      delta_best: null,
    }));
}

/**
 * Recent runs, newest first: the hub's `recent` (else the timeline), each failure with its
 * stderr path, plus the failure groups none of those rows covers. `failures` holds failed and
 * lost runs, archived too: the timeline gives each its status, and archived ones are left out
 * when the hub sends `recent` (an older hub's timeline fallback has no other way to show them).
 */
export function recentRows(summary: OverviewSummary, max = 12): RecentRow[] {
  const failures = new Map(summary.failures.map((f) => [f.run_id, f]));
  const names = summary.names ?? {};
  const rows: RecentRow[] = (summary.recent ?? fromTimeline(summary)).slice(0, max).map((r) => {
    const f = failures.get(r.run_id);
    return {
      runId: r.run_id,
      owner:r.owner,
      at: r.created_at,
      name: names[r.run_id] ?? r.name,
      project: r.project,
      task: r.task,
      status: r.status,
      reason: reasonText(r.status, r.exit_code ?? f?.exit_code ?? null, r.end_reason),
      score: r.primary,
      deltaBest: r.delta_best,
      by: r.created_by,
      hypothesis: r.hypothesis,
      stderr: f?.stderr_path ?? null,
      retried: f?.retried_ok ?? false,
      count: 1,
    };
  });
  const shown = new Set(rows.map((r) => r.runId));
  const items = new Map(summary.timeline.map((t) => [t.run_id, t]));
  const statusOf = (f: FailureRow): RunStatus => (items.get(f.run_id)?.status === "lost" ? "lost" : "failed");
  const extra = summary.failures.filter((f) => !(summary.recent && items.get(f.run_id)?.archived));
  for (const status of ["failed", "lost"] as const) {
    for (const group of groupFailures(extra.filter((f) => statusOf(f) === status))) {
      const f = group[0];
      if (!f || group.some((g) => shown.has(g.run_id))) continue;
      const item = items.get(f.run_id);
      rows.push({
        runId: f.run_id,
        owner:f.owner,
        at: f.created_at,
        name: names[f.run_id] ?? f.label,
        project: item?.project ?? "",
        task: item?.task ?? null,
        status,
        reason: reasonText(status, f.exit_code, null),
        score: null,
        deltaBest: null,
        by: item?.created_by ?? "",
        hypothesis: "",
        stderr: f.stderr_path,
        retried: group.every((g) => g.retried_ok),
        count: group.length,
      });
    }
  }
  return rows.sort((a, b) => parseTime(b.at) - parseTime(a.at));
}
