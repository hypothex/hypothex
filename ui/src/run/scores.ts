/**
 * The Overview tab's numbers (spec 4.3): one tile per metric@version/key of the run, the
 * primary first, Δ against the config's seed mean (muted inside one sample sd), and the
 * "Where it ranks" strip on the primary metric.
 */
import type { ScoreRecord, Stats, TaskGroup, TaskRun, TaskRuns } from "../api/models";
import type { StripMark } from "../charts/ScoreStrip";
import { ordinal } from "../pages/components/remote";
import { latestScores } from "../pages/components/ScoresList";

export interface ScoreTile {
  id: string;
  label: string;
  metric: string;
  value: number | null;
  error: string | null;
  primary: boolean;
  old: boolean;
  /** This run minus the config's seed mean; null for old versions, failed scores and single seeds. */
  delta: number | null;
  sd: number | null;
  /** |Δ| is under one sd of the config's seeds (or the seeds agree). */
  noise: boolean;
  /** Δ is better in the metric's direction; null when the direction is unknown or Δ is noise. */
  better: boolean | null;
}

export interface TileContext {
  /** `metric/key` of the task's primary (`TaskRuns.primary`); null without a task. */
  primary: string | null;
  higherIsBetter: boolean;
  /** The task's current version per metric; null: the newest version among the run's scores. */
  versions: Readonly<Record<string, string>> | null;
  /** This run and its sibling seeds (TaskRun.scores by `metric/key`). */
  group: readonly Pick<TaskRun, "run_id" | "scores">[];
}

const byVersion = (a: string, b: string): number => a.localeCompare(b, undefined, { numeric: true });

export function currentVersions(scores: readonly ScoreRecord[], versions: Readonly<Record<string, string>> | null): Record<string, string> {
  const out: Record<string, string> = { ...(versions ?? {}) };
  for (const s of scores) {
    if (versions && versions[s.metric] !== undefined) continue;
    const seen = out[s.metric];
    if (seen === undefined || byVersion(s.version, seen) > 0) out[s.metric] = s.version;
  }
  return out;
}

/** Mean and sample sd; null for fewer than two values. */
export function meanSd(values: readonly number[]): { mean: number; sd: number } | null {
  if (values.length < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const sd = Math.sqrt(values.reduce((a, v) => a + (v - mean) ** 2, 0) / (values.length - 1));
  return { mean, sd };
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function scoreTiles(scores: readonly ScoreRecord[], ctx: TileContext): ScoreTile[] {
  const current = currentVersions(scores, ctx.versions);
  const [pMetric = "", pKey = "value"] = (ctx.primary ?? "").split("/");
  const tiles = latestScores([...scores])
    .filter((s) => s.key !== "*")
    .map((s): ScoreTile => {
      const old = current[s.metric] !== s.version;
      const scoreKey = `${s.metric}/${s.key}`;
      const value = s.error === null && finite(s.value) ? s.value : null;
      const stats = old || value === null ? null : meanSd(ctx.group.map((r) => r.scores[scoreKey]).filter(finite));
      const delta = stats && value !== null ? value - stats.mean : null;
      const noise = stats !== null && delta !== null && (delta === 0 || Math.abs(delta) < stats.sd);
      const better = delta === null || noise || s.metric !== pMetric ? null : ctx.higherIsBetter ? delta > 0 : delta < 0;
      return {
        id: `${s.metric}@${s.version}/${s.key}`,
        label: `${s.metric}@${s.version}${s.key === "value" ? "" : `/${s.key}`}`,
        metric: s.metric,
        value,
        error: s.error,
        primary: !old && s.metric === pMetric && s.key === pKey,
        old,
        delta,
        sd: stats?.sd ?? null,
        noise,
        better,
      };
    });
  return tiles.sort((a, b) => Number(b.primary) - Number(a.primary) || Number(a.old) - Number(b.old) || a.label.localeCompare(b.label));
}

export type { StripMark };

export interface RankModel {
  marks: StripMark[];
  /** The best config's 95% test-set interval (green band); null when it has none. */
  band: [number, number] | null;
  /** `2nd of 3 seeds · config is best of 12`. */
  summary: string;
  seeds: number;
  configs: number;
  color: string;
}

type Scored<T, K extends keyof T> = T & { [P in K]: NonNullable<T[P]> };

export function rankModel(data: TaskRuns, runId: string, color: string): RankModel | null {
  const me = data.runs.find((r) => r.run_id === runId);
  if (!me || me.primary === null) return null;
  const order = (a: number, b: number): number => (data.higher_is_better ? b - a : a - b);
  const configs = data.groups
    .filter((g): g is Scored<TaskGroup, "primary"> => g.primary !== null)
    .sort((a, b) => order((a.primary as Stats).mean, (b.primary as Stats).mean));
  const seeds = data.runs
    .filter((r): r is Scored<TaskRun, "primary"> => r.group_id === me.group_id && r.primary !== null)
    .sort((a, b) => order(a.primary, b.primary));
  const seedRank = seeds.findIndex((r) => r.run_id === runId) + 1;
  const configRank = configs.findIndex((g) => g.group_id === me.group_id) + 1;
  const best = configs[0];
  const marks: StripMark[] = [
    ...configs.filter((g) => g.group_id !== me.group_id).map((g): StripMark => ({ kind: "other", value: g.primary.mean })),
    ...seeds.filter((r) => r.run_id !== runId).map((r): StripMark => ({ kind: "seed", value: r.primary, color })),
    { kind: "this", value: me.primary, color },
  ];
  const seedText = seeds.length > 1 ? `${ordinal(seedRank)} of ${seeds.length} seeds` : "1 seed";
  const configText =
    configRank === 0 ? `${configs.length} configs` : `config is ${configRank === 1 ? "best" : ordinal(configRank)} of ${configs.length}`;
  return {
    marks,
    band: best?.test_interval ? [best.test_interval.lo, best.test_interval.hi] : null,
    summary: `${seedText} · ${configText}`,
    seeds: seeds.length,
    configs: configs.length,
    color,
  };
}
