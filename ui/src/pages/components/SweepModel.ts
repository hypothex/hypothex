/**
 * Pure helpers for the Sweep page (spec 8A.6, contract 1.7).
 *
 * `summarize_sweep` cells arrive as JSON objects; `parseCells` turns them into typed rows
 * and tolerates missing fields (a server without `std`/`runs` still renders). A queued or
 * running run on a host that is not connected is shown `stale`: derived here, never stored.
 * Runs are matched to hosts by `environment_id` (`hostRowForRun`), never `executor.host`.
 */
import type { HostRow, Leaderboard, RunRecord, RunStatus, SweepSpec } from "../../api/models";
import { DASH, fmtScore, isNum, parseTime } from "./format";
import { hostRowForRun } from "./HostsPanel";

// ------------------------------------------------------------------------------- cells
/** A run of a cell, as the summary lists it. `status` is null when the server sent none. */
export interface SweepCellRun {
  run_id: string;
  status: RunStatus | null;
  seed: number | null;
}

/** One param combination of a sweep (a `summarize_sweep` cell). */
export interface SweepCellRow {
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

/** A short age: `42s`, `4m`, `1h 30m`. Negative ages are 0. */
export function fmtAge(seconds: number): string {
  const s = Math.max(0, seconds);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** The runs table's state text: `stale 4m`, `queued, pos 2`, `queued, job 48211`, `running, c0412`, `failed, exit 1`. */
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
      return Number.isNaN(t) ? "stale" : `stale ${fmtAge((now - t) / 1000)}`;
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
