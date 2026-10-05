/**
 * Pure helpers for the Sweep page (spec 8A.6, contract 1.7).
 *
 * `summarize_sweep` cells arrive as JSON objects; `parseCells` turns them into typed rows
 * and tolerates missing fields (a server without `std`/`runs` still renders). A queued or
 * running run on a host that is not connected is shown `stale`: derived here, never stored.
 * Runs are matched to hosts by `environment_id` (`hostRowForRun`), never `executor.host`.
 */
import type { HostRow, Leaderboard, RunRecord, RunStatus, StatItem, SweepSpec } from "../../api/models";
import { cliQuote } from "../../launch/cli";
import {
  DASH,
  fmtDuration,
  fmtInterval,
  fmtScore,
  fmtScoreUnit,
  fmtUsd,
  isNum,
  parseTime,
  runSeconds,
  shortId,
} from "./format";
import { fmtAgeMs, hostRowForRun } from "./HostsPanel";

// ------------------------------------------------------------------------------- cells
/** A run of a cell, as the summary lists it. `status` is null when the server sent none. */
export interface SweepCellRun {
  run_id: string;
  status: RunStatus | null;
  seed: number | null;
}

/** One param combination of a sweep (a `summarize_sweep` cell). */
export interface SweepCellRow {
  uncounted?: number;
  params: Record<string, string>;
  group_id: string | null;
  /** Scored seeds. */
  n: number;
  mean: number | null;
  lo: number | null;
  hi: number | null;
  std: number | null;
  run_ids: string[];
  runs: SweepCellRun[];
}

/** What a run glyph shows: a run status, or `stale` for a queued or running run on a host that is not connected. */
export type RunGlyphState = RunStatus | "stale";

const STATUSES: ReadonlySet<string> = new Set(["queued", "running", "finished", "failed", "killed", "lost"]);

const numOrNull = (v: unknown): number | null => (isNum(v) ? v : null);

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function cellRun(v: unknown): SweepCellRun | null {
  const r = asRecord(v);
  if (r === null || typeof r.run_id !== "string") return null;
  const status = typeof r.status === "string" && STATUSES.has(r.status) ? (r.status as RunStatus) : null;
  return { run_id: r.run_id, status, seed: numOrNull(r.seed) };
}

/**
 * Read one summary cell; null when it has no `params` object.
 *
 * Param values become strings; without a `runs` list the run ids are listed with an
 * unknown status.
 */
export function parseCell(raw: unknown): SweepCellRow | null {
  const r = asRecord(raw);
  const p = asRecord(r?.params);
  if (r === null || p === null) return null;
  const params = Object.fromEntries(Object.entries(p).map(([k, v]) => [k, String(v)]));
  const ids = Array.isArray(r.run_ids) ? r.run_ids.filter((x): x is string => typeof x === "string") : [];
  const listed = Array.isArray(r.runs) ? r.runs.map(cellRun).filter((x): x is SweepCellRun => x !== null) : [];
  const runs = listed.length > 0 ? listed : ids.map((run_id) => ({ run_id, status: null, seed: null }));
  return {
    params,
    group_id: typeof r.group_id === "string" ? r.group_id : null,
    n: isNum(r.n) ? r.n : 0,
    uncounted: isNum(r.uncounted) ? r.uncounted : 0,
    mean: numOrNull(r.mean),
    lo: numOrNull(r.lo),
    hi: numOrNull(r.hi),
    std: numOrNull(r.std),
    run_ids: ids.length > 0 ? ids : runs.map((x) => x.run_id),
    runs,
  };
}

/** Every readable cell, in the server's (expansion) order. */
export function parseCells(cells: readonly unknown[]): SweepCellRow[] {
  return cells.map(parseCell).filter((c): c is SweepCellRow => c !== null);
}

/** Same keys with the same values. */
export function sameParams(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k]);
}

// ---------------------------------------------------------------------------- run state
/**
 * The hub's name for the host a run executes on: the `GET /api/v1/hosts` row that serves
 * the run's environment (`local` for a hub run). Without a matching row (the list is not
 * loaded, or it failed) the machine's own hostname, `record.host`. Never `executor.host`:
 * the backend writes that same machine hostname there, not the hub's name.
 */
export function hostOf(record: RunRecord, hosts: readonly HostRow[] | undefined): string {
  return hostRowForRun(record, hosts)?.name ?? record.host;
}

/**
 * Environment id → ISO time its host left `connected`, for every host that is not connected
 * (stale, error, disabled, ...; contract 1.5, spec 5.6). Keyed by environment, the way the
 * backend matches runs to hosts.
 */
export function staleHosts(hosts: readonly HostRow[] | undefined): Map<string, string> {
  const out = new Map<string, string>();
  for (const h of hosts ?? []) {
    const env = h.state.environment_id;
    if (env && h.state.state !== "connected") out.set(env, h.state.since);
  }
  return out;
}

/**
 * The state a run is drawn with.
 *
 * The record's status wins; a run not indexed yet uses the cell's status (else `queued`).
 * A queued or running run whose environment is in `stale` is `stale` (the run page shows
 * the same run as stale).
 */
export function runState(
  record: RunRecord | undefined,
  fallback: RunStatus | null,
  stale: ReadonlyMap<string, string>,
): RunGlyphState {
  const status = record?.status ?? fallback ?? "queued";
  const active = status === "queued" || status === "running";
  if (active && record !== undefined && stale.has(record.environment_id)) return "stale";
  return status;
}

/**
 * A duration in seconds: `42s`, `4m`, `1h 30m`. Negative durations are 0.
 *
 * The run page's wait times use it (`fmtWait`). The stale age in `stateText` uses
 * `fmtAgeMs` instead, so it reads the same as the host row.
 */
export function fmtAge(seconds: number): string {
  const s = Math.max(0, seconds);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** The runs table's state text (stale age as the host row prints it): `stale 4m`, `queued, pos 2`, `queued, job 48211`, `running, c0412`, `failed, exit 1`. */
export function stateText(
  record: RunRecord,
  state: RunGlyphState,
  stale: ReadonlyMap<string, string>,
  now: number,
): string {
  const ex = record.executor;
  switch (state) {
    case "stale": {
      const since = stale.get(record.environment_id);
      const t = since === undefined ? Number.NaN : parseTime(since);
      return Number.isNaN(t) ? "stale" : `stale ${fmtAgeMs(now - t)}`;
    }
    case "queued":
      if (ex.queue_position != null) return `queued, pos ${ex.queue_position}`;
      if (ex.slurm_job_id != null) return `queued, job ${ex.slurm_job_id}`;
      return "queued";
    case "running":
      return ex.node != null ? `running, ${ex.node}` : "running";
    case "failed":
      return record.exit_code !== null ? `failed, exit ${record.exit_code}` : "failed";
    default:
      return state;
  }
}

// ---------------------------------------------------------------------- axes and ranking
/** Rows and columns of the heat table. */
export interface HeatAxes {
  row: string;
  col: string;
  rows: string[];
  cols: string[];
}

/** Heat axes for exactly two listed params (first = rows); null otherwise (use the table). */
export function heatAxes(spec: SweepSpec): HeatAxes | null {
  if (spec.grid.length !== 2) return null;
  const [a, b] = spec.grid;
  if (!a?.values || !b?.values) return null;
  return { row: a.name, col: b.name, rows: a.values.map(String), cols: b.values.map(String) };
}

/** Scored cells, best first in the metric's direction (ties keep expansion order). */
export function rankCells(cells: readonly SweepCellRow[], higherIsBetter: boolean): SweepCellRow[] {
  const sign = higherIsBetter ? -1 : 1;
  return cells.filter((c) => c.mean !== null).sort((a, b) => sign * ((a.mean ?? 0) - (b.mean ?? 0)));
}

/** 0 at the worst mean, 1 at the best; 1 when every mean is equal. */
export function heatLevel(mean: number, lo: number, hi: number, higherIsBetter: boolean): number {
  if (hi === lo) return 1;
  const t = (mean - lo) / (hi - lo);
  return higherIsBetter ? t : 1 - t;
}

/** Ink share of a heat cell in percent: 4 % (worst) to 34 % (best), as in the mockup. */
export function heatPercent(level: number): number {
  return Math.round(4 + level * 30);
}

// ---------------------------------------------------------------------------- labels
/** `3e-4, 10`: the cell's values in param order. */
export function cellLabel(params: Record<string, string>, names: readonly string[]): string {
  return names.map((n) => params[n] ?? DASH).join(", ");
}

/** `lr 3e-4, beam 10`. */
export function paramsText(params: Record<string, string>, names: readonly string[]): string {
  return names.map((n) => `${n} ${params[n] ?? DASH}`).join(", ");
}

/** `lr 3 × beam 3 × 3 seeds`; sampled params show their range, `N samples` follows. */
export function gridLabel(spec: SweepSpec): string {
  const parts = spec.grid.map((p) =>
    p.values ? `${p.name} ${p.values.length}` : `${p.name} ${p.low ?? DASH}–${p.high ?? DASH}${p.log ? " log" : ""}`,
  );
  if (spec.random != null) parts.push(`${spec.random} samples`);
  parts.push(`${spec.seeds.length} seed${spec.seeds.length === 1 ? "" : "s"}`);
  return parts.join(" × ");
}

/** Mean of the finite values, null without any. */
export function meanOf(values: readonly (number | null)[]): number | null {
  const xs = values.filter(isNum);
  return xs.length > 0 ? xs.reduce((s, v) => s + v, 0) / xs.length : null;
}

/**
 * Per-seed primary values of a cell's own runs, for the seed dots.
 *
 * The values come from the task leaderboard row of the cell's group, but only when every run
 * of that row is one of the cell's runs: then they are exactly the population of the cell's
 * mean and 95% CI (the backend scores the cell on the sweep's runs only). When the group also
 * holds runs outside the cell (the same config ran before the sweep), the row's seed values
 * mix them in and cannot be split per run, so the cell shows no dots. Empty without a row.
 */
export function seedValues(cell: SweepCellRow, board: Leaderboard | undefined): number[] {
  if (board === undefined || cell.group_id === null) return [];
  const row = board.rows.find((r) => r.group_id === cell.group_id);
  if (row === undefined) return [];
  const own = new Set(cell.run_ids);
  if (!row.run_ids.every((id) => own.has(id))) return [];
  return row.seed_values[board.primary] ?? [];
}

/** Hover text of a cell: params, mean over seeds, seed values, 95% interval, seed σ. */
export function cellTip(cell: SweepCellRow, names: readonly string[], seeds: readonly number[]): string {
  const lines = [paramsText(cell.params, names)];
  if (cell.uncounted) lines.push(`${cell.uncounted} uncounted runs (excluded from score)`);
  if (cell.mean === null) {
    lines.push("no scored runs yet");
    return lines.join("\n");
  }
  lines.push(`mean ${fmtScore(cell.mean)} over ${cell.n} seed${cell.n === 1 ? "" : "s"}`);
  if (seeds.length > 0) lines.push(`seeds ${seeds.map((v) => fmtScore(v)).join(", ")}`);
  if (cell.lo !== null && cell.hi !== null) lines.push(`95% CI ${fmtScore(cell.lo)}–${fmtScore(cell.hi)}`);
  if (cell.std !== null) lines.push(`seed σ ${fmtScore(cell.std)}`);
  return lines.join("\n");
}

// ------------------------------------------------------------------------- runs, links
/** Runs in the sweep's launch order (`SweepSummary.run_ids`); others last, oldest first. */
export function orderRuns(runs: readonly RunRecord[], order: readonly string[]): RunRecord[] {
  const at = new Map(order.map((id, i) => [id, i]));
  const pos = (r: RunRecord): number => at.get(r.run_id) ?? order.length;
  return [...runs].sort(
    (a, b) =>
      pos(a) - pos(b) || parseTime(a.created_at) - parseTime(b.created_at) || a.run_id.localeCompare(b.run_id),
  );
}

/** Hosts the runs execute on (`hostOf`), each once, in run order. */
export function hostsOf(runs: readonly RunRecord[], hosts: readonly HostRow[] | undefined): string[] {
  return [...new Set(runs.map((r) => hostOf(r, hosts)))];
}

/** In-app link to a sweep page. */
export function sweepHref(project: string, sweepId: string): string {
  return `/s/${encodeURIComponent(project)}/${encodeURIComponent(sweepId)}`;
}

// ---------------------------------------------------------------------- actions
/** Most seeds one Add seeds click may add per cell. */
export const MAX_NEW_SEEDS = 20;

/**
 * `--seeds` text. A single number is a count to the CLI (`--seeds 5` means 1 to 5), so one
 * seed other than 1 is written as the one-element list `5,`.
 */
function seedsArg(seeds: readonly number[]): string {
  const [only] = seeds;
  return seeds.length === 1 && only !== 1 ? `${only},` : seeds.join(",");
}

/**
 * The `hx sweep` command that launches the same sweep (spec 8A.6).
 *
 * `--gpus` and `-H` come from the sweep's runs; `--queue` is added when any run is or was
 * queued on a host. Every argument goes through `cliQuote` (as in the Launch dialog), so
 * `{lr}` or `--x={1,2}` is quoted and the shell neither drops nor brace-expands it.
 */
export function sweepCli(spec: SweepSpec, runs: readonly RunRecord[]): string {
  const argv = ["hx", "sweep"];
  if (spec.task) argv.push("-t", spec.task);
  for (const p of spec.grid) if (p.values) argv.push("--grid", `${p.name}=${p.values.join(",")}`);
  if (spec.random != null) {
    argv.push("--random", String(spec.random));
    for (const p of spec.grid) {
      if (!p.values) argv.push("--param", `${p.name}=${p.low ?? ""}:${p.high ?? ""}${p.log ? ":log" : ""}`);
    }
  }
  argv.push("--seeds", seedsArg(spec.seeds));
  if (spec.host) argv.push("--host", spec.host);
  const gpus = runs.find((r) => (r.gpus_requested ?? 0) > 0)?.gpus_requested ?? 0;
  if (gpus > 0) argv.push("--gpus", String(gpus));
  if (runs.some((r) => r.status === "queued" || r.executor.queue_position != null)) argv.push("--queue");
  const hypothesis = runs.map((r) => r.hypothesis.trim()).find((h) => h !== "");
  if (hypothesis) argv.push("-H", hypothesis);
  return `${argv.map(cliQuote).join(" ")} -- ${spec.command_template.map(cliQuote).join(" ")}`;
}

/** `count` new seeds after the largest seed in use (`[1, 2]`, 2 → `[3, 4]`): the Launch dialog's helper. */
export { nextSeeds } from "../../launch/seeds";

/** A whole number from 1 to `MAX_NEW_SEEDS`, else null. */
export function parseSeedCount(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= MAX_NEW_SEEDS ? n : null;
}

// ------------------------------------------------------------------ time and cost
function median(xs: readonly number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? (s[mid] ?? 0) : ((s[mid - 1] ?? 0) + (s[mid] ?? 0)) / 2;
}

/**
 * Seconds until the sweep is done: median finished run time × (queued runs + time left
 * of running runs) ÷ runs running now. Null without a finished run or with nothing left.
 */
export function etaSeconds(runs: readonly RunRecord[], now: number): number | null {
  const done = runs
    .filter((r) => r.status === "finished")
    .map((r) => runSeconds(r, now))
    .filter(isNum);
  const running = runs.filter((r) => r.status === "running");
  const queued = runs.filter((r) => r.status === "queued").length;
  if (done.length === 0 || running.length + queued === 0) return null;
  const typical = median(done);
  const left =
    queued * typical + running.reduce((s, r) => s + Math.max(0, typical - (runSeconds(r, now) ?? 0)), 0);
  return left / Math.max(running.length, 1);
}

/**
 * GPUs a run is billed for, as the backend's `billed_gpus`: the GPUs it holds; a SLURM run
 * whose node reported no indices, the GPUs it asked for (SLURM reserved that many).
 */
function billedGpus(record: RunRecord): number {
  const held = (record.executor.gpus ?? []).length;
  if (held > 0) return held;
  return record.executor.slurm_job_id ? (record.gpus_requested ?? 0) : 0;
}

/** GPU-hours of a run: its final `cost.gpu_hours`, else wall time so far × billed GPUs. */
export function gpuHours(record: RunRecord, now: number): number {
  if (record.cost) return record.cost.gpu_hours;
  const seconds = runSeconds(record, now) ?? 0;
  return (seconds * billedGpus(record)) / 3600;
}

/** GPU-hours per host (`hostOf`), in run order; hosts with no GPU time are left out. */
export function gpuHoursByHost(
  runs: readonly RunRecord[],
  now: number,
  hosts: readonly HostRow[] | undefined,
): Map<string, number> {
  const out = new Map<string, number>();
  for (const r of runs) {
    const h = gpuHours(r, now);
    const host = hostOf(r, hosts);
    if (h > 0) out.set(host, (out.get(host) ?? 0) + h);
  }
  return out;
}

/** `6.2` below 10, `102` from 10. */
export function fmtGpuHours(hours: number): string {
  return hours < 10 ? hours.toFixed(1) : hours.toFixed(0);
}

/** A run's dollars: final `cost.total_usd`, else API spend so far, else null. */
export function runUsd(record: RunRecord): number | null {
  if (record.cost) return record.cost.total_usd;
  return record.usage && record.usage.usd > 0 ? record.usage.usd : null;
}

// ----------------------------------------------------------------------- progress
/** Progress segment: finished, running, queued, failed or lost, killed, not indexed yet. */
export type ProgressKind = "f" | "r" | "q" | "x" | "k" | "n";

function progressParts(counts: Readonly<Record<string, number>>): [ProgressKind, number][] {
  const c = (k: string): number => counts[k] ?? 0;
  const parts: [ProgressKind, number][] = [
    ["f", c("finished")],
    ["r", c("running")],
    ["q", c("queued")],
    ["x", c("failed") + c("lost")],
    ["k", c("killed")],
  ];
  const known = parts.reduce((s, [, n]) => s + n, 0);
  parts.push(["n", Math.max(0, c("total") - known)]);
  return parts;
}

/** One segment per run, in the order finished, running, queued, failed, killed, pending. */
export function progressSegments(counts: Readonly<Record<string, number>>): ProgressKind[] {
  return progressParts(counts).flatMap(([kind, n]) => Array.from({ length: n }, () => kind));
}

const PROGRESS_WORD: Record<ProgressKind, string> = {
  f: "finished",
  r: "running",
  q: "queued",
  x: "failed",
  k: "killed",
  n: "pending",
};

/** `5 finished, 1 running, 1 queued, 1 failed` (+ killed and pending when present). */
export function progressLabel(counts: Readonly<Record<string, number>>): string {
  return progressParts(counts)
    .filter(([kind, n]) => n > 0 || kind === "f" || kind === "r" || kind === "q" || kind === "x")
    .map(([kind, n]) => `${n} ${PROGRESS_WORD[kind]}`)
    .join(", ");
}

// --------------------------------------------------------------------------- sort
/**
 * Sort keys of the built-in `n` and metric columns. The `#` keeps them apart from param
 * names, which the backend limits to `^[A-Za-z_][A-Za-z0-9_.]*$` (so a param may be `n`).
 */
export const SORT_N = "#n";
export const SORT_MEAN = "#mean";

/** Sort column (a param name, `SORT_N` or `SORT_MEAN`) and direction. */
export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

/** Best cell first: by mean, descending when higher is better. */
export function defaultSort(higherIsBetter: boolean): SortState {
  return { key: SORT_MEAN, dir: higherIsBetter ? "desc" : "asc" };
}

/** Clicking the active column flips it; another column starts ascending (the metric: best first). */
export function nextSort(prev: SortState, key: string, higherIsBetter: boolean): SortState {
  if (prev.key === key) return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
  return key === SORT_MEAN ? defaultSort(higherIsBetter) : { key, dir: "asc" };
}

const NUMERIC = /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i;

function sortValue(cell: SweepCellRow, key: string): number | string | null {
  if (key === SORT_MEAN) return cell.mean;
  if (key === SORT_N) return cell.n;
  const v = cell.params[key];
  if (v === undefined) return null;
  return NUMERIC.test(v.trim()) ? Number(v) : v;
}

/** Cells sorted by `sort`; numbers (also `1e-4`-style params) compare as numbers, gaps last. */
export function sortCells(cells: readonly SweepCellRow[], sort: SortState): SweepCellRow[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return cells
    .map((cell, i) => ({ cell, i, v: sortValue(cell, sort.key) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === b.v ? a.i - b.i : a.v === null ? 1 : -1;
      const d =
        typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : String(a.v).localeCompare(String(b.v));
      return d !== 0 ? sign * d : a.i - b.i;
    })
    .map((x) => x.cell);
}

// -------------------------------------------------------------------------- stats
/** Inputs of the sweep stat strip. */
export interface SweepStatsInput {
  counts: Readonly<Record<string, number>>;
  totalUsd: number;
  best: SweepCellRow | null;
  names: readonly string[];
  metric: string;
  unit: string;
  /** The sweep's runs, in launch order. */
  runs: readonly RunRecord[];
  /** `GET /api/v1/hosts`, to name each run's host (undefined while it loads or fails). */
  hosts: readonly HostRow[] | undefined;
  now: number;
}

const failLine = (r: RunRecord): string =>
  `${shortId(r.run_id)} ${r.status}${r.exit_code !== null ? `, exit ${r.exit_code}` : ""}`;

/** Stat strip: best, 95% CI, finished / total, running, queued, failed, cost with GPU-h, ETA. */
export function sweepStats(input: SweepStatsInput): StatItem[] {
  const { counts, names, metric, unit, runs, hosts, now } = input;
  const c = (k: string): number => counts[k] ?? 0;
  const hours = gpuHoursByHost(runs, now, hosts);
  const total = [...hours.values()].reduce((s, h) => s + h, 0);
  const failed = runs.filter((r) => r.status === "failed" || r.status === "lost");
  const eta = etaSeconds(runs, now);
  const best = input.best !== null && input.best.mean !== null ? input.best : null;
  const seeds = (n: number): string => `${n} seed${n === 1 ? "" : "s"}`;
  return [
    {
      label: `best ${metric}`,
      value: best ? fmtScoreUnit(best.mean, unit) : DASH,
      tooltip: best
        ? `Mean ${metric} of ${paramsText(best.params, names)} over ${seeds(best.n)}`
        : "No scored runs yet",
    },
    {
      label: "95% CI",
      value: best && best.lo !== null && best.hi !== null ? fmtInterval(best.lo, best.hi) : DASH,
      tooltip: "Best cell: test-set 95% interval, or over seeds without per-example scores",
    },
    { label: "finished", value: String(c("finished")), unit: `/ ${c("total")}`, tooltip: "Runs finished" },
    { label: "running", value: String(c("running")), tooltip: "Runs running now" },
    { label: "queued", value: String(c("queued")), tooltip: "Runs waiting in a host queue" },
    {
      label: "failed",
      value: String(c("failed") + c("lost")),
      tooltip: failed.length > 0 ? failed.map(failLine).join("\n") : "No failed runs",
    },
    {
      label: `cost, ${fmtGpuHours(total)} GPU-h`,
      value: input.totalUsd > 0 ? fmtUsd(input.totalUsd) : "$0",
      tooltip:
        hours.size > 0
          ? [...hours].map(([host, h]) => `${host} ${fmtGpuHours(h)} GPU-h`).join("\n")
          : "No GPU time yet",
    },
    {
      label: "ETA",
      value: eta === null ? DASH : fmtDuration(eta),
      tooltip: "Median finished run time × runs left ÷ runs running",
    },
  ];
}
