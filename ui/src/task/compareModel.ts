/**
 * The Compare panel's model (spec 4.2): score keys `<prefix>/<dataset>.<model>.<metric>`
 * (or `<dataset>.<metric>`) with the primary's prefix, split by `splitKey`. Defaults: the
 * first four datasets, the primary's model, the primary's metric, table. Multi-selects
 * keep at least one value. A row's best value is marked only between two or more
 * distinct values.
 */
import type { PanelSpec } from "../api/models";
import { type KeyParts, partRoles, splitKey } from "../lib/scoreKeys";

export type CompareRender = "table" | "bars";

export interface CompareState {
  datasets: string[];
  model: string | null;
  metrics: string[];
  render: CompareRender;
}

export interface CompareKey extends KeyParts {
  key: string;
}

export interface CompareLabels {
  datasets: string;
  model: string;
  metrics: string;
}

export interface CompareModel {
  keys: CompareKey[];
  datasets: string[];
  models: string[];
  metrics: string[];
  labels: CompareLabels;
}

/** One table column / bar series: a visible identity and its scores by key. */
export interface CompareColumn {
  id: string;
  name: string;
  color: string;
  scores: Readonly<Record<string, number | null | undefined>>;
}

export interface CompareRow {
  metric: string;
  dataset: string;
  values: (number | null)[];
  best: number | null;
}

/** A `views/query` row of a saved `compare` panel. */
export interface CompareResultRow {
  dataset: string;
  model: string | null;
  metric: string;
  key: string;
  run_id: string;
  group_id: string;
  name: string;
  value: number | null;
  /** The key's direction (`leaderboard.key_higher_is_better`); absent from older servers. */
  higher_is_better?: boolean;
}

export const DEFAULT_DATASETS = 4;

const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * Control labels from `hypothex.yaml` `score_keys` names, the dataset and model parts
 * resolved as `splitKey` does (`partRoles`): `{split}.{arch}.{metric}` → Splits, Arch;
 * `{model}.{dataset}.{metric}` → Datasets, Model.
 */
export function compareLabels(names?: readonly string[] | null): CompareLabels {
  const roles = partRoles(names);
  return {
    datasets: `${cap(roles?.dataset ?? "dataset")}s`,
    model: cap(roles?.model ?? "model"),
    metrics: "Metrics",
  };
}

function uniq(values: readonly (string | null)[]): string[] {
  return [...new Set(values.filter((v): v is string => v !== null))];
}

export function compareModel(keys: readonly string[], primary: string, names?: readonly string[] | null): CompareModel | null {
  const prefix = splitKey(primary, names).prefix;
  const parsed = [...new Set(keys)]
    .map((key): CompareKey => ({ key, ...splitKey(key, names) }))
    .filter((k) => k.prefix === prefix && k.dataset !== null);
  const datasets = uniq(parsed.map((k) => k.dataset));
  if (datasets.length < 2) return null;
  return {
    keys: parsed,
    datasets,
    models: uniq(parsed.map((k) => k.model)),
    metrics: uniq(parsed.map((k) => k.metric)),
    labels: compareLabels(names),
  };
}

export function defaultCompare(model: CompareModel, primary: string, names?: readonly string[] | null): CompareState {
  const prim = splitKey(primary, names);
  return {
    datasets: model.datasets.slice(0, DEFAULT_DATASETS),
    model: prim.model !== null && model.models.includes(prim.model) ? prim.model : (model.models[0] ?? null),
    metrics: [model.metrics.includes(prim.metric) ? prim.metric : (model.metrics[0] as string)],
    render: "table",
  };
}

/** Toggle `value`; the last selected value cannot be removed; the result keeps `order`. */
export function toggleKeepOne(selected: readonly string[], value: string, order: readonly string[]): string[] {
  if (selected.includes(value)) return selected.length > 1 ? selected.filter((v) => v !== value) : [...selected];
  const next = new Set([...selected, value]);
  return order.filter((v) => next.has(v));
}

export function compareKeyFor(model: CompareModel, dataset: string, modelName: string | null, metric: string): string | undefined {
  return model.keys.find((k) => k.dataset === dataset && k.model === modelName && k.metric === metric)?.key;
}

/**
 * The best of two or more distinct finite values in the given direction, else null (one
 * value, or all equal, marks nothing). Shared with the Score keys bars.
 */
export function rowBest(values: readonly (number | null)[], higherIsBetter: boolean): number | null {
  const v = values.filter((x): x is number => x !== null && Number.isFinite(x));
  if (v.length < 2 || new Set(v).size < 2) return null;
  return higherIsBetter ? Math.max(...v) : Math.min(...v);
}

/** One row per selected metric × dataset; each row's best in its key's direction (`higherIsBetter(key)`). */
export function compareRows(
  model: CompareModel,
  state: CompareState,
  columns: readonly CompareColumn[],
  higherIsBetter: (key: string) => boolean,
): CompareRow[] {
  const metrics = model.metrics.filter((m) => state.metrics.includes(m));
  const datasets = model.datasets.filter((d) => state.datasets.includes(d));
  return metrics.flatMap((metric) =>
    datasets.map((dataset) => {
      const key = compareKeyFor(model, dataset, state.model, metric);
      const values = columns.map((c) => (key === undefined ? null : (c.scores[key] ?? null)));
      return { metric, dataset, values, best: key === undefined ? null : rowBest(values, higherIsBetter(key)) };
    }),
  );
}

/** Panel title: `Compare datasets · model-x` (no model part: `Compare datasets`). */
export function compareTitle(state: CompareState, labels: CompareLabels): string {
  return `Compare ${labels.datasets.toLowerCase()}${state.model ? ` · ${state.model}` : ""}`;
}

/**
 * One title per Compare panel, all distinct: a repeat of an earlier title gets ` · 2`,
 * ` · 3`, ... (a view must not have two panels with the same title).
 */
export function compareTitles(states: readonly CompareState[], labels: CompareLabels): string[] {
  const used = new Set<string>();
  return states.map((state) => {
    const base = compareTitle(state, labels);
    let title = base;
    for (let n = 2; used.has(title); n++) title = `${base} · ${n}`;
    used.add(title);
    return title;
  });
}

/** The view panel "Save as view" writes (`type: compare`); `title` defaults to `compareTitle`. */
export function comparePanelSpec(state: CompareState, labels: CompareLabels, title: string = compareTitle(state, labels)): PanelSpec {
  return {
    type: "compare",
    title,
    data: { datasets: [...state.datasets], model: state.model, metrics: [...state.metrics] },
    render: state.render,
  };
}

/**
 * A saved compare panel's rows as a model, one column per group, everything selected;
 * `directions` holds each key's direction where its rows carry one.
 */
export function compareFromRows(rows: readonly CompareResultRow[]): {
  model: CompareModel;
  columns: Omit<CompareColumn, "color">[];
  state: Omit<CompareState, "render">;
  directions: Record<string, boolean>;
} | null {
  if (rows.length === 0) return null;
  const keys = new Map<string, CompareKey>();
  const directions: Record<string, boolean> = {};
  const columns = new Map<string, { id: string; name: string; scores: Record<string, number | null> }>();
  for (const r of rows) {
    if (!keys.has(r.key)) {
      const cut = r.key.indexOf("/");
      keys.set(r.key, { key: r.key, prefix: cut > 0 ? r.key.slice(0, cut) : "", dataset: r.dataset, model: r.model, metric: r.metric });
    }
    if (typeof r.higher_is_better === "boolean") directions[r.key] = r.higher_is_better;
    const id = r.group_id || r.run_id;
    const col = columns.get(id) ?? { id, name: r.name, scores: {} };
    col.scores[r.key] = r.value;
    columns.set(id, col);
  }
  const list = [...keys.values()];
  const model: CompareModel = {
    keys: list,
    datasets: uniq(list.map((k) => k.dataset)),
    models: uniq(list.map((k) => k.model)),
    metrics: uniq(list.map((k) => k.metric)),
    labels: compareLabels(null),
  };
  return {
    model,
    columns: [...columns.values()],
    state: { datasets: model.datasets, model: list[0]?.model ?? null, metrics: model.metrics },
    directions,
  };
}
