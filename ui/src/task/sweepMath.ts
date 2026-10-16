/**
 * Sweeps tab math (spec 4.2 "Sweeps"): the task's sweeps, "What matters" (share of the
 * primary metric's variance per param, from the cells; formula in `whatMatters`), the
 * best cell against the next one, and the parallel-coordinates axes and lines (the chart
 * colours lines by the score axis on its own sequential ramp).
 */
import type { SweepSpec, TaskRuns } from "../api/models";
import type { PCAxis, PCLine } from "../charts/ParallelCoords";
import { type SweepCellRow, rankCells } from "../pages/components/SweepModel";
import { runLabel } from "./useRunSelection";

/** Sweep ids of the task's runs, the sweep with the newest run first. */
export function taskSweepIds(data: TaskRuns): string[] {
  const out: string[] = [];
  for (const r of [...data.runs].sort((a, b) => b.created_at.localeCompare(a.created_at))) {
    if (r.sweep_id && !out.includes(r.sweep_id)) out.push(r.sweep_id);
  }
  return out;
}

export interface Importance {
  name: string;
  share: number;
}

/**
 * Share of variance per param, their interaction and the seeds.
 *
 * With `n_c` scored seeds, mean `m_c` and seed sd `s_c` per cell, `N = Σ n_c` and
 * `M = Σ n_c·m_c / N`: `SS_p = Σ_v n_v (m_v − M)²` over the values `v` of param `p`
 * (`n_v`, `m_v` pooled over the cells with `p = v`); `interaction = max(0, Σ n_c (m_c − M)²
 * − Σ_p SS_p)`; `SS_seed = Σ (n_c − 1) s_c²`. Each share is its SS over
 * `Σ_p SS_p + interaction + SS_seed`.
 */
export function whatMatters(cells: readonly SweepCellRow[], names: readonly string[]): Importance[] {
  const scored = cells.filter((c): c is SweepCellRow & { mean: number } => c.mean !== null && c.n > 0);
  const total = scored.reduce((a, c) => a + c.n, 0);
  if (total === 0) return [];
  const grand = scored.reduce((a, c) => a + c.n * c.mean, 0) / total;
  const between = scored.reduce((a, c) => a + c.n * (c.mean - grand) ** 2, 0);
  const seed = scored.reduce((a, c) => a + (c.n - 1) * (c.std ?? 0) ** 2, 0);
  const main = names.map((name) => {
    const levels = new Map<string, { n: number; sum: number }>();
    for (const c of scored) {
      const v = c.params[name] ?? "";
      const level = levels.get(v) ?? { n: 0, sum: 0 };
      level.n += c.n;
      level.sum += c.n * c.mean;
      levels.set(v, level);
    }
    let ss = 0;
    for (const level of levels.values()) ss += level.n * (level.sum / level.n - grand) ** 2;
    return { name, ss };
  });
  const mainTotal = main.reduce((a, m) => a + m.ss, 0);
  const interaction = Math.max(0, between - mainTotal);
  const denominator = mainTotal + interaction + seed;
  if (denominator <= 1e-15) return [];
  const params = main.map((m) => ({ name: m.name, share: m.ss / denominator })).sort((a, b) => b.share - a.share);
  const inter = interaction / denominator;
  return [...params, ...(inter >= 0.005 ? [{ name: "interaction", share: inter }] : []), { name: "seed", share: seed / denominator }];
}

/** Key of the score axis (`#` keeps it apart from param names, which are identifiers). */
export const SCORE_AXIS = "#score";

export interface BestComparison {
  best: SweepCellRow;
  next: SweepCellRow | null;
  delta: number | null;
  /** The two cells' 95% intervals overlap; null when either has none. */
  overlap: boolean | null;
}

export function bestComparison(cells: readonly SweepCellRow[], higherIsBetter: boolean): BestComparison | null {
  const ranked = rankCells(cells, higherIsBetter);
  const best = ranked[0];
  if (!best || best.mean === null) return null;
  const next = ranked[1];
  if (!next || next.mean === null) return { best, next: null, delta: null, overlap: null };
  const overlap =
    best.lo !== null && best.hi !== null && next.lo !== null && next.hi !== null ? next.lo <= best.hi && best.lo <= next.hi : null;
  return { best, next, delta: best.mean - next.mean, overlap };
}

/** One line per scored run of the sweep: its grid values and the primary (`SCORE_AXIS`). */
export function sweepLines(data: TaskRuns, spec: SweepSpec): PCLine[] {
  return data.runs
    .filter((r) => r.sweep_id === spec.id && r.primary !== null)
    .map((r) => {
      const values: Record<string, string | number | null> = { [SCORE_AXIS]: r.primary };
      for (const p of spec.grid) {
        const raw = r.params[p.name];
        values[p.name] = raw === undefined ? null : p.values ? raw : Number.isFinite(Number(raw)) ? Number(raw) : null;
      }
      return { id: r.run_id, name: runLabel(r), values };
    });
}

/** One axis per grid param (listed values: categorical; sampled ranges: numeric), then the score. */
export function parallelAxes(spec: SweepSpec, metric: string): PCAxis[] {
  return [
    ...spec.grid.map((p): PCAxis => (p.values ? { key: p.name, label: p.name, values: p.values.map(String) } : { key: p.name, label: p.name })),
    { key: SCORE_AXIS, label: metric },
  ];
}
