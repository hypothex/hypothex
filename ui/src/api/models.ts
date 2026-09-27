/**
 * Response and body shapes of the Hypothex HTTP API.
 *
 * Hand-written from the phase 1b interface contract
 * (docs/superpowers/plans/2026-09-27-hypothex-phase1b-contract.md, sections 1-2) and the
 * phase 1a pydantic models. Most routes return `dict[str, Any]`, so the generated
 * `types.ts` knows their paths but not their bodies; these types fill that gap.
 */

export type RunStatus = "queued" | "running" | "finished" | "failed" | "killed" | "lost";
export type TaskKind = "generic" | "training" | "agent_eval" | "agent_iteration" | "system_bench";
export type PanelType =
  | "stat_strip"
  | "leaderboard"
  | "curves"
  | "scatter"
  | "distribution"
  | "grid"
  | "table"
  | "trace"
  | "markdown"
  | "vega_lite";
export type Source = "runs" | "scores" | "metrics" | "predictions" | "samples" | "usage" | "traces";
/** Log streams `GET /runs/{id}/logs` serves. */
export type LogStream = "stdout" | "stderr" | "supervisor";

// records ------------------------------------------------------------------------------
export interface GitInfo {
  repo: string | null;
  commit: string | null;
  branch: string | null;
  dirty: boolean;
  untracked_count: number;
  untracked: string[];
}

export interface DatasetRef {
  name: string;
  version: string;
  split: string | null;
  host: string;
  path: string;
  hash: string | null;
  hash_mode: string | null;
  size: number | null;
  checked_at: string | null;
}

export interface Artifact {
  kind: string;
  path: string;
  host: string;
  size: number | null;
  step: number | null;
  metrics: Record<string, number>;
}

export interface ExecutorInfo {
  type: string;
  pid: number | null;
  pid_create_time: number | null;
  child_pid: number | null;
}

export interface UsageTotals {
  tokens_in: number;
  tokens_out: number;
  usd: number;
  seconds: number;
  calls: number;
}

export interface RunRecord {
  run_id: string;
  project: string;
  task: string | null;
  hypothesis: string;
  kind: "full" | "infer";
  parent: string | null;
  stage: string | null;
  command: string[];
  command_template: string[];
  vars: Record<string, string>;
  params: Record<string, string>;
  cwd: string;
  environment_id: string;
  host: string;
  executor: ExecutorInfo;
  git: GitInfo;
  datasets: DatasetRef[];
  seed: number | null;
  config_hash: string;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  exit_code: number | null;
  artifacts: Artifact[];
  tags: string[];
  starred: boolean;
  archived: boolean;
  created_by: string;
  usage: UsageTotals | null;
}

export interface ScoreRecord {
  metric: string;
  version: string;
  key: string;
  value: number | null;
  error: string | null;
  source_hash: string | null;
  created_at: string;
}

export interface MetricPoint {
  name: string;
  step: number;
  value: number;
  t: number | null;
}

export interface Stats {
  mean: number;
  std: number;
  n: number;
  ci_low: number | null;
  ci_high: number | null;
}

// projects, tasks, runs ------------------------------------------------------------------
export interface ProjectInfo {
  project: string;
  repo: string;
  description: string;
  tasks: string[];
}

export interface TaskSummary {
  project: string;
  name: string;
  description: string;
  dataset: string;
  dataset_version: string;
  split: string | null;
  metrics: Record<string, string>;
  primary: string;
  higher_is_better: boolean;
  n_runs: number;
  best: number | null;
}

export interface TaskDetail {
  summary: TaskSummary;
  repo: string;
  dataset: { name: string } & Record<string, unknown>;
  metrics: Record<string, Record<string, unknown>>;
  stages: Record<string, unknown>;
}

export interface RunDetail {
  record: RunRecord;
  scores: ScoreRecord[];
  paths: Record<string, string>;
  notes: string;
  has_diff: boolean;
  metric_names: string[];
  children: string[];
}

export interface PredictionRow {
  id: string;
  prediction: unknown;
  reference: unknown;
  scores: Record<string, Record<string, unknown>>;
}

export interface PredictionPage {
  run_id: string;
  total: number;
  offset: number;
  limit: number;
  rows: PredictionRow[];
}

export interface ExampleDiff {
  a: string;
  b: string;
  metric: string;
  field: string;
  fixed: string[];
  broken: string[];
  both_pass: number;
  both_fail: number;
}

export interface LogChunk {
  stream: string;
  text: string;
  offset: number;
  size: number;
}

export interface RunsQuery {
  project?: string;
  task?: string;
  status?: RunStatus;
  tag?: string;
  archived?: boolean;
  limit?: number;
}

export interface PredictionsQuery {
  offset?: number;
  limit?: number;
  metric?: string;
  failures_only?: boolean;
  field?: string;
}

// leaderboard (contract 1.7) -------------------------------------------------------------
export interface NoiseInterval {
  lo: number;
  hi: number;
  method: "wilson" | "bootstrap";
  n: number;
}

export interface VersusBest {
  delta: number;
  p: number | null;
  fixed: number | null;
  broken: number | null;
  test: "sign" | "paired_bootstrap" | "welch" | null;
  examples_needed: number | null;
}

/** One stat in a stat strip: a number with a short label; the explanation is the tooltip. */
export interface StatItem {
  label: string;
  value: number | string | null;
  unit?: string | null;
  tooltip?: string | null;
}

export interface LeaderboardRow {
  group_id: string;
  run_ids: string[];
  latest_run_id: string;
  hypothesis: string;
  commit: string | null;
  config_hash: string;
  n: number;
  scores: Record<string, Stats>;
  primary: Stats | null;
  single_seed: boolean;
  within_noise_of_best: boolean | null;
  label: string;
  seed_values: Record<string, number[]>;
  identical_seeds: boolean;
  test_interval: NoiseInterval | null;
  vs_best: VersusBest | null;
  created_by: string[];
  usage: UsageTotals | null;
}

export interface Leaderboard {
  project: string;
  task: string;
  primary: string;
  higher_is_better: boolean;
  metric_versions: Record<string, string>;
  rows: LeaderboardRow[];
  needs_reeval: string[];
  unscored: string[];
  headline: string;
  kind: TaskKind;
  stat_strip: StatItem[];
}

// overview (contract 1.9) ----------------------------------------------------------------
export interface TimelineItem {
  run_id: string;
  project: string;
  task: string | null;
  created_at: string;
  created_by: string;
  status: RunStatus;
  archived: boolean;
  group_id: string | null;
  is_best: boolean;
  label: string;
}

export interface IdeaRow {
  project: string;
  task: string | null;
  group_id: string;
  label: string;
  created_by: string;
  created_at: string;
  statuses: RunStatus[];
  primary: Stats | null;
  test_interval: NoiseInterval | null;
  identical_seeds: boolean;
  best_band: NoiseInterval | null;
}

export interface FailureRow {
  run_id: string;
  label: string;
  exit_code: number | null;
  created_at: string;
  stderr_path: string;
  retried_ok: boolean;
}

export interface ProjectRow {
  project: string;
  task: string;
  runs: number;
  best: number | null;
  kind: TaskKind;
}

export interface OverviewSummary {
  headline: string;
  counts: Record<string, number>;
  timeline: TimelineItem[];
  ideas: IdeaRow[];
  running: RunRecord[];
  failures: FailureRow[];
  projects: ProjectRow[];
}

// views and panels (contract 1.4, 1.6) --------------------------------------------------
export interface RunFilter {
  status?: string[] | null;
  tags?: string[] | null;
  created_by?: string | null;
  since?: string | null;
}

export interface PanelLayout {
  span?: number;
  row?: number | null;
}

export interface PanelData {
  metrics?: string[] | null;
  x?: string | null;
  y?: string | null;
  group_by?: "group" | "config" | "run" | "seed" | null;
  filter?: Record<string, unknown> | null;
  pick?: "best" | "latest" | "all" | null;
  source?: Source | null;
  fields?: string[] | null;
  run_id?: string | null;
  example_id?: string | null;
  step_metric?: string | null;
}

export interface PanelSpec {
  type: PanelType;
  title?: string;
  data?: PanelData;
  layout?: PanelLayout;
  noise?: ("seed" | "test_set")[];
  pareto?: Record<string, "min" | "max"> | null;
  spec?: Record<string, unknown> | null;
  text?: string | null;
  scale?: "linear" | "log";
  render?: "chart" | "table";
}

export interface ViewSpec {
  title: string;
  from?: TaskKind | null;
  runs?: RunFilter;
  panels?: PanelSpec[];
}

export interface ValidationIssue {
  line: number | null;
  path: string;
  message: string;
  suggestion: string | null;
}

export interface ViewInfo {
  name: string;
  title: string;
  origin: "preset" | "inline" | "file";
  path: string | null;
  kind: TaskKind | null;
}

/** `GET .../views/{name}`: the stored YAML text and the resolved view. */
export interface ViewDocument {
  info: ViewInfo;
  text: string;
  view: ViewSpec;
}

export interface SavedView {
  info: ViewInfo;
  view: ViewSpec;
}

export interface ViewValidation {
  ok: boolean;
  issues: ValidationIssue[];
  /** The view resolved (`resolve_view`): `from:` preset panels with layouts first, no `from`. */
  view?: ViewSpec | null;
}

export interface ViewQueryBody {
  view?: ViewSpec;
  name?: string;
  panel?: PanelSpec;
}

export interface PanelResult {
  type: PanelType;
  title: string;
  rows: Record<string, unknown>[];
  meta: Record<string, unknown>;
}

export interface ViewQueryResult {
  panels: PanelResult[];
}

// panel row shapes (contract 1.6; keys exact) --------------------------------------------
export interface CurvesRow {
  run_id: string;
  group_id: string;
  seed: number | null;
  name: string;
  step: number;
  value: number;
}

/** `x` is text on an ordinal axis (`meta.x_type = "ordinal"`, e.g. versions), else a number. */
export interface ScatterRow {
  group_id: string;
  label: string;
  x: number | string;
  x_lo: number | null;
  x_hi: number | null;
  y: number;
  y_lo: number | null;
  y_hi: number | null;
  seeds: { x: number | string; y: number }[];
  pareto: boolean;
  /** Ordinal x only: worse than the best earlier row by more than its 95% CI. */
  regression: boolean;
}

/** Scatter `meta` (contract 1.6). The UI takes the y direction and best group from here. */
export interface ScatterMeta {
  /** Resolved x reference, e.g. `usage.usd` or `version`. */
  x: string;
  /** Resolved y reference; `data.y` defaults to the task primary. */
  y: string;
  x_type: "quantitative" | "ordinal";
  scale: "linear" | "log";
  /** The panel's Pareto directions; null when the view sets none (then no row is on a front). */
  pareto: { x?: "min" | "max"; y?: "min" | "max" } | null;
  /** Direction of the y metric, whatever `pareto` says (`usage.*` cost and time are lower-is-better). */
  y_higher_is_better: boolean;
  /** Group with the best mean y in that direction; null when no row qualifies. */
  best_group: string | null;
}

/** `[delta_rel, lo, hi]`: relative change vs the baseline and its 95% bootstrap CI. */
export type DeltaCI = [number, number | null, number | null];

export interface DistributionRow {
  group_id: string;
  label: string;
  n: number;
  p50: number;
  p95: number;
  p99: number;
  ecdf: [number, number][];
  seeds: { run_id: string; p50: number; p95: number; p99: number }[];
  /** Change vs the task's baseline group; null on the baseline row or with no baseline. */
  vs_baseline: { p50: DeltaCI; p95: DeltaCI; p99: DeltaCI } | null;
}

export interface GridRow {
  item_id: string;
  group_id: string;
  value: number;
}

export interface TraceRow {
  turn: number;
  tool: string | null;
  args: unknown;
  result: unknown;
  tokens_in: number | null;
  tokens_out: number | null;
  seconds: number | null;
  error: string | null;
}

// traces and kinds ------------------------------------------------------------------------
export interface TraceSummary {
  example_id: string;
  turns: number;
  failed: boolean;
}

export interface TaskKindInfo {
  kind: TaskKind;
  run_view: PanelSpec[];
}

// actions and events ----------------------------------------------------------------------
export interface ActionOptions {
  /** Idempotency key; a fresh UUID is used when omitted. */
  command_id?: string;
  created_by?: string;
}

export interface HxEvent {
  sequence: number;
  type: string;
  project: string | null;
  run_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

/** Messages the server sends on `/api/v1/ws`. */
export type WsMessage =
  | { type: "event"; event: HxEvent }
  | { type: "ready"; last_sequence: number }
  | { type: "error"; error: string };

export interface EvalReport {
  evaluated: string[];
  skipped: Record<string, string>;
  warnings: string[];
}
