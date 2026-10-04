/**
 * `curves` panel: small multiples of metric histories.
 *
 * One column per seed group, one row per metric, on one shared step axis; a metric whose
 * steps span a very different range (e.g. a sweep logged with step = concurrency) goes
 * below the others with its own axis. A metric with fewer than 2 points in every group is
 * no curve: it is shown as a value (the seed mean) above the rows. A series with one point
 * next to longer ones is a dot. Seeds are
 * faint lines, the seed mean is bold. The best checkpoint of each run is a green
 * dot; loss spikes and non-finite values (`NaN <step>`) are dashed red lines with a
 * spike glyph, killed or failed runs end in a red cross. Values pushed off the panel by a spike get a red caret with
 * their number.
 */
import { bisectCenter } from "d3-array";
import { area, line } from "d3-shape";
import { useId, useMemo, useState, type MouseEvent, type ReactElement } from "react";
import { AxisBottom, AxisLeftLabels, GridY } from "../charts/Axis";
import { CheckpointMark, Key, KillMark, SpikeMark, type KeyItem } from "../charts/Glyphs";
import {
  fmtValue,
  kStep,
  linear,
  logScale,
  useElementWidth,
  type LinearScale,
} from "../charts/Scale";
import { useTooltip } from "../charts/Tooltip";
import type { CurvesRow } from "../api/models";
import type { PanelProps } from "./index";

/** One `curves` row as sent by the server (contract 1.6). */
export type CurvePoint = CurvesRow;

/** `meta.checkpoints[]`. */
export interface CheckpointJson {
  run_id: string;
  step: number;
  value: number;
  best: boolean;
}

/** `meta.events[]`. */
export interface EventJson {
  run_id: string;
  step: number;
  kind: "spike" | "killed" | "failed" | "nonfinite";
  /** Short text from the server, e.g. `spike 9k`, `killed 14k`, `NaN 9k`. */
  label?: string;
}

/**
 * `meta.groups[]`. With `group_by: run` each entry is one run: `label` is already
 * `<config> r<n>`, `seed_group` is the run's seed group and `repeat` its `n`.
 */
export interface GroupJson {
  group_id: string;
  label: string;
  seed_group?: string;
  repeat?: number;
}

/**
 * Column titles for `groups`: `label`, else the group id. Titles that still repeat (one
 * column per run of the same idea, without the server's run labels) get the run's seed
 * (`baseline s2`) when the column holds a single seed (and the seeds differ), else a
 * counter (`baseline #2`), never a mix.
 */
export function columnTitles(groups: GroupJson[], seedsOf: (groupId: string) => (number | null)[]): GroupJson[] {
  const base = groups.map((g) => (typeof g.label === "string" && g.label.trim() ? g.label.trim() : g.group_id));
  const oneSeed = (id: string): number | null => {
    const seeds = [...new Set(seedsOf(id))];
    return seeds.length === 1 && typeof seeds[0] === "number" ? seeds[0] : null;
  };
  const members = new Map<string, GroupJson[]>();
  groups.forEach((g, i) => {
    const b = base[i] ?? g.group_id;
    members.set(b, [...(members.get(b) ?? []), g]);
  });
  // seeds name the columns only when every column of the label has its own distinct seed
  const bySeed = new Set(
    [...members.entries()]
      .filter(([, gs]) => {
        const seeds = gs.map((g) => oneSeed(g.group_id));
        return seeds.every((x) => x !== null) && new Set(seeds).size === seeds.length;
      })
      .map(([b]) => b),
  );
  const seen = new Map<string, number>();
  return groups.map((g, i) => {
    const b = base[i] ?? g.group_id;
    if ((members.get(b)?.length ?? 0) < 2) return { ...g, label: b };
    const k = (seen.get(b) ?? 0) + 1;
    seen.set(b, k);
    return { ...g, label: bySeed.has(b) ? `${b} s${oneSeed(g.group_id)}` : `${b} #${k}` };
  });
}

/** One run's points for one metric, sorted by step. */
export interface RunSeries {
  run_id: string;
  seed: number | null;
  points: Array<[number, number]>;
}

/** One small multiple: a group's runs for one metric plus their mean. */
export interface Cell {
  runs: RunSeries[];
  mean: Array<[number, number]>;
}

/** How a metric row is scaled. */
export interface RowScale {
  kind: "log" | "linear" | "lr";
  domain: [number, number];
}

/** A best checkpoint placed on a metric row. */
export interface PlacedCheckpoint extends CheckpointJson {
  name: string;
  group_id: string;
}

/** Everything the panel draws, computed from the rows and meta. */
export interface CurvesModel {
  /** Groups with any points, curves or values. */
  groups: GroupJson[];
  /** Metrics drawn as curves, one row each. */
  names: string[];
  /** Metrics with fewer than 2 points (steps) in every group: shown as values, not rows. */
  values: string[];
  cells: Map<string, Cell>;
  /** Last step of the shared axis. */
  maxStep: number;
  /** Last step of each metric. */
  rowMax: Record<string, number>;
  /** Metrics drawn on their own step axis (after the shared rows). */
  ownAxis: string[];
  scales: Record<string, RowScale>;
  checkpoints: PlacedCheckpoint[];
  events: Array<EventJson & { group_id: string }>;
}

/** Most columns per band of small multiples. */
export const MAX_COLS = 3;
/** Width of the row-label gutter. */
export const LABEL_W = 104;
/**
 * Width of the row-label gutter: at least {@link LABEL_W}, wider when a metric name plus
 * its y tick labels would not fit (12 px names, 11 px ticks), at most 220 px.
 */
export function labelGutter(model: CurvesModel): number {
  let need = 0;
  for (const name of model.names) {
    const scale = model.scales[name] ?? { kind: "linear", domain: [0, 1] };
    const ticks = yScaleFor(scale, 0, ROW_H).ticks.map(fmtValue);
    const tickW = Math.max(0, ...ticks.map((t) => Math.ceil(t.length * 11 * 0.6)));
    need = Math.max(need, Math.ceil(name.length * 12 * 0.56) + tickW + 22);
  }
  return Math.min(220, Math.max(LABEL_W, need));
}

/** Gap between columns. */
export const COL_GAP = 36;
/** Height of the column-title strip. */
export const TITLE_H = 34;
/** Height of a metric row, and of the learning-rate row. */
export const ROW_H = 116;
export const LR_ROW_H = 40;
/** Gap between metric rows. */
export const ROW_GAP = 16;
/** Space for an x axis under a row that is not the last. */
export const AXIS_GAP = 30;
/** A metric whose last step is this many times off the median metric's gets its own axis. */
export const OWN_AXIS_RATIO = 2;

/**
 * Metrics whose step range is far from the others (last step more than
 * {@link OWN_AXIS_RATIO} times above or below the median metric's last step).
 */
export function ownAxisNames(rowMax: Record<string, number>): string[] {
  const names = Object.keys(rowMax);
  if (names.length < 2) return [];
  const sorted = names.map((n) => rowMax[n] ?? 0).sort((a, b) => a - b);
  const median = sorted[Math.floor((sorted.length - 1) / 2)] ?? 0;
  if (median <= 0) return [];
  return names.filter((n) => {
    const m = rowMax[n] ?? 0;
    return m > median * OWN_AXIS_RATIO || m * OWN_AXIS_RATIO < median;
  });
}

/** Share of the step axis after a spike that is left out of the y-domain. */
export const SPIKE_WINDOW = 0.1;

/** True for learning-rate metric names (`lr`, `learning_rate`, `train/lr`). */
export function isLr(name: string): boolean {
  return /(^|[/_.])lr$|learning_rate$/.test(name);
}

/** True for system metrics logged beside the model's (`sys/gpu_util`, `system.mem`). */
export function isSystem(name: string): boolean {
  return /^sys(tem)?[/._]/.test(name);
}

/** True for loss metric names. */
export function isLoss(name: string): boolean {
  return /loss/i.test(name);
}

/** Key of a cell in {@link CurvesModel.cells}. */
export const cellKey = (group: string, name: string): string => `${group}\u0000${name}`;

/** Average the runs at every step where at least one run has a value. */
export function meanSeries(runs: RunSeries[]): Array<[number, number]> {
  const by = new Map<number, number[]>();
  for (const r of runs) {
    for (const [s, v] of r.points) {
      const list = by.get(s);
      if (list) list.push(v);
      else by.set(s, [v]);
    }
  }
  return [...by.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([s, vs]) => [s, vs.reduce((a, b) => a + b, 0) / vs.length]);
}

/** The value in effect at `step`: the last point at or before it, or `null`. */
export function valueAt(points: Array<[number, number]>, step: number): number | null {
  let out: number | null = null;
  for (const [s, v] of points) {
    if (s > step) break;
    out = v;
  }
  return out;
}

function assignName(
  ck: CheckpointJson,
  names: string[],
  byRun: Map<string, Map<string, RunSeries>>,
): string | null {
  const series = byRun.get(ck.run_id);
  for (const name of names) {
    const pts = series?.get(name)?.points ?? [];
    const hit = pts.find(([s, v]) => s === ck.step && Math.abs(v - ck.value) <= 1e-9 * Math.max(1, Math.abs(v)));
    if (hit) return name;
  }
  const plain = names.filter((n) => !isLr(n) && !isLoss(n));
  return plain.at(-1) ?? names.filter((n) => !isLr(n)).at(-1) ?? null;
}

/**
 * Turn `curves` rows and meta into drawable cells, scales, checkpoints, and events.
 *
 * Parameters
 * ----------
 * rows : CurvePoint[]
 *     Metric points, any order.
 * meta : object
 *     `groups`, `checkpoints`, `events` as in the contract; all optional.
 *
 * Returns
 * -------
 * CurvesModel
 *     Groups in `meta.groups` order (unknown groups appended, groups with no points
 *     dropped), metric names in
 *     `meta.metrics` order (else first-seen), system metrics after the model's and
 *     learning-rate rows last, and per-row scales. Metrics with fewer than 2 steps in
 *     every group go to `values` (same order) instead of the rows. Points of a
 *     spiked run within {@link SPIKE_WINDOW} of the axis after the spike are left
 *     out of the y-domain so one spike does not flatten every other line. The
 *     shared step axis reaches the last `nonfinite` event of a drawn run, so a
 *     NaN after a run's last finite point stays on the chart.
 */
export function buildCurves(rows: CurvePoint[], meta: Record<string, unknown> | undefined): CurvesModel {
  const metaGroups = Array.isArray(meta?.groups) ? (meta.groups as GroupJson[]) : [];
  const events = Array.isArray(meta?.events) ? (meta.events as EventJson[]) : [];
  const cks = Array.isArray(meta?.checkpoints) ? (meta.checkpoints as CheckpointJson[]) : [];

  const groups: GroupJson[] = [...metaGroups];
  const known = new Set(groups.map((g) => g.group_id));
  const names: string[] = [];
  const runGroup = new Map<string, string>();
  const byRun = new Map<string, Map<string, RunSeries>>();
  const rowMax: Record<string, number> = {};
  const stepsOf = new Map<string, Set<number>>();
  /** Metrics with 2 or more steps in some group: drawn as curves. */
  const lined = new Set<string>();
  for (const p of rows) {
    if (!Number.isFinite(p.value) || !Number.isFinite(p.step)) continue;
    if (!known.has(p.group_id)) {
      known.add(p.group_id);
      groups.push({ group_id: p.group_id, label: p.group_id });
    }
    if (!names.includes(p.name)) names.push(p.name);
    runGroup.set(p.run_id, p.group_id);
    let series = byRun.get(p.run_id);
    if (!series) byRun.set(p.run_id, (series = new Map()));
    let rs = series.get(p.name);
    if (!rs) series.set(p.name, (rs = { run_id: p.run_id, seed: p.seed, points: [] }));
    rs.points.push([p.step, p.value]);
    rowMax[p.name] = Math.max(rowMax[p.name] ?? 0, p.step);
    const key = cellKey(p.group_id, p.name);
    const steps = stepsOf.get(key) ?? new Set<number>();
    stepsOf.set(key, steps.add(p.step));
    if (steps.size > 1) lined.add(p.name);
  }
  // a metric with one step in every group is a value: no line, no step axis of its own
  const values = names.filter((n) => !lined.has(n));
  names.splice(0, names.length, ...names.filter((n) => lined.has(n)));
  const ownAxis = ownAxisNames(Object.fromEntries(names.map((n) => [n, rowMax[n] ?? 0])));
  const own = (n: string): number => (ownAxis.includes(n) ? 1 : 0);
  // the view's metric order when given; system metrics (`sys/...`) below the model's
  const listed = Array.isArray(meta?.metrics) ? (meta.metrics as unknown[]) : [];
  const at = (n: string): number => {
    const i = listed.indexOf(n);
    return i < 0 ? listed.length : i;
  };
  const order = (a: string, b: string): number =>
    own(a) - own(b) ||
    Number(isLr(a)) - Number(isLr(b)) ||
    Number(isSystem(a)) - Number(isSystem(b)) ||
    at(a) - at(b);
  names.sort(order);
  values.sort(order);
  const shared = names.filter((n) => !ownAxis.includes(n));
  // a run that diverged and never logged again has its NaN past its last finite point
  const nanSteps = events
    .filter((e) => e.kind === "nonfinite" && runGroup.has(e.run_id) && Number.isFinite(e.step))
    .map((e) => e.step);
  const maxStep = Math.max(0, ...shared.map((n) => rowMax[n] ?? 0), ...nanSteps);

  const cells = new Map<string, Cell>();
  for (const series of byRun.values()) {
    for (const [name, rs] of series) {
      rs.points.sort((a, b) => a[0] - b[0]);
      const key = cellKey(runGroup.get(rs.run_id) ?? "", name);
      const cell = cells.get(key);
      if (cell) cell.runs.push(rs);
      else cells.set(key, { runs: [rs], mean: [] });
    }
  }
  for (const cell of cells.values()) {
    cell.runs.sort((a, b) => (a.seed ?? 0) - (b.seed ?? 0) || a.run_id.localeCompare(b.run_id));
    cell.mean = meanSeries(cell.runs);
  }

  const spikes = events.filter((e) => e.kind === "spike");
  const scales: Record<string, RowScale> = {};
  for (const name of names) {
    const window = SPIKE_WINDOW * (rowMax[name] ?? 0);
    const vals: number[] = [];
    for (const [runId, series] of byRun) {
      const own = spikes.filter((e) => e.run_id === runId);
      for (const [s, v] of series.get(name)?.points ?? []) {
        if (own.some((e) => s >= e.step && s <= e.step + window)) continue;
        vals.push(v);
      }
    }
    const lo = vals.length ? Math.min(...vals) : 0;
    const hi = vals.length ? Math.max(...vals) : 1;
    if (isLr(name)) {
      scales[name] = { kind: "lr", domain: [0, hi > 0 ? hi : 1] };
    } else if (isLoss(name) && lo > 0) {
      scales[name] = { kind: "log", domain: [lo * 0.9, hi * 1.1] };
    } else {
      const pad = (hi - lo || Math.abs(hi) || 1) * 0.05;
      scales[name] = { kind: "linear", domain: [lo - pad, hi + pad] };
    }
  }

  const checkpoints: PlacedCheckpoint[] = [];
  for (const ck of cks) {
    if (!ck.best) continue;
    const name = assignName(ck, names, byRun);
    const group = runGroup.get(ck.run_id);
    if (name && group) checkpoints.push({ ...ck, name, group_id: group });
  }
  const seedsByGroup = new Map<string, (number | null)[]>();
  for (const series of byRun.values()) {
    const rs = series.values().next().value;
    if (!rs) continue;
    const g = runGroup.get(rs.run_id) ?? "";
    const list = seedsByGroup.get(g) ?? [];
    list.push(rs.seed);
    seedsByGroup.set(g, list);
  }
  // a group with no points at all (e.g. a run that failed before logging) gets no empty column
  const drawn = groups.filter((g) => [...names, ...values].some((n) => cells.has(cellKey(g.group_id, n))));
  return {
    groups: columnTitles(drawn, (id) => seedsByGroup.get(id) ?? []),
    names,
    values,
    cells,
    maxStep,
    rowMax,
    ownAxis,
    scales,
    checkpoints,
    events: events
      .filter((e) => runGroup.has(e.run_id))
      .map((e) => ({ ...e, group_id: runGroup.get(e.run_id) ?? "" })),
  };
}

function yScaleFor(scale: RowScale, top: number, h: number): LinearScale {
  if (scale.kind === "log") return logScale(scale.domain, top + h, top);
  return linear(scale.domain, top + h, top, 3);
}

interface RowGeom {
  name: string;
  top: number;
  h: number;
  /** Draw an x axis under this row (the last shared row before own-axis rows, and own-axis rows). */
  axis: boolean;
}

function rowGeometry(names: string[], ownAxis: string[] = []): { rows: RowGeom[]; bottom: number } {
  let y = TITLE_H;
  const lastShared = names.filter((n) => !ownAxis.includes(n)).at(-1);
  const rows = names.map((name, i) => {
    const h = isLr(name) ? LR_ROW_H : ROW_H;
    const last = i === names.length - 1;
    const axis = ownAxis.includes(name) || (name === lastShared && ownAxis.length > 0);
    const r = { name, top: y, h, axis: axis && !last };
    y += h + (axis && !last ? AXIS_GAP : ROW_GAP);
    return r;
  });
  return { rows, bottom: y - ROW_GAP };
}

function Caret({ x, y, up, v }: { x: number; y: number; up: boolean; v: number }): ReactElement {
  const d = up
    ? `M${x - 4} ${y + 5}L${x} ${y - 1}L${x + 4} ${y + 5}Z`
    : `M${x - 4} ${y - 5}L${x} ${y + 1}L${x + 4} ${y - 5}Z`;
  return (
    <g className="clip-caret">
      <path className="clipm" d={d} />
      <text className="lbl-s" x={up ? x + 8 : x - 8} y={up ? y + 6 : y - 1} textAnchor={up ? "start" : "end"}>
        {fmtValue(v)}
      </text>
    </g>
  );
}

interface StackProps {
  model: CurvesModel;
  groups: GroupJson[];
  width: number;
  cols: number;
  onHover: (text: string | null, x: number, y: number) => void;
}

function CurveStack({ model, groups, width, cols, onHover }: StackProps): ReactElement {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  // the hovered column and the mouse's x in svg pixels; each row maps it to its own step
  const [hover, setHover] = useState<{ col: number; px: number } | null>(null);
  const gutter = labelGutter(model);
  const colW = Math.max(40, (width - gutter - COL_GAP * (cols - 1)) / cols);
  const { rows, bottom } = rowGeometry(model.names, model.ownAxis);
  const H = bottom + 30;
  const xTicks = linear([0, model.maxStep || 1], 0, 1, 4).ticks;
  const own = (name: string): boolean => model.ownAxis.includes(name);
  const rowStepMax = (name: string): number => (own(name) ? model.rowMax[name] || 1 : model.maxStep || 1);
  const shared = model.names.filter((n) => !own(n));

  const columns = groups.map((g, ci) => {
    const x0 = gutter + ci * (colW + COL_GAP);
    const x = linear([0, model.maxStep || 1], x0, x0 + colW, 4);
    const runIds = new Set(
      model.names.flatMap((n) => model.cells.get(cellKey(g.group_id, n))?.runs.map((r) => r.run_id) ?? []),
    );
    const meanSteps = (names: string[]): number[] =>
      [
        ...new Set(names.flatMap((n) => model.cells.get(cellKey(g.group_id, n))?.mean.map((p) => p[0]) ?? [])),
      ].sort((a, b) => a - b);
    const sharedSteps = meanSteps(shared);
    const ownSteps = new Map(model.ownAxis.map((n) => [n, meanSteps([n])]));
    /** The x scale of one row: the column's shared scale, or the row's own step range. */
    const xOf = (name: string) => (own(name) ? linear([0, rowStepMax(name)], x0, x0 + colW, 4) : x);
    /** The row's mean step nearest to pixel `px` on that row's own x scale. */
    const stepAt = (name: string, px: number): number | null => {
      const steps = own(name) ? (ownSteps.get(name) ?? []) : sharedSteps;
      return steps[bisectCenter(steps, xOf(name).invert(px))] ?? null;
    };
    return { g, ci, x0, x, runIds, xOf, stepAt };
  });

  const tipText = (col: (typeof columns)[number], px: number): string => {
    const head = shared.length > 0 ? col.stepAt(shared[0] ?? "", px) : null;
    const lines = [head == null ? col.g.label : `${col.g.label}, step ${head.toLocaleString("en-US")}`];
    for (const name of model.names) {
      const cell = model.cells.get(cellKey(col.g.group_id, name));
      const step = col.stepAt(name, px);
      if (!cell || step == null) continue;
      const parts = cell.runs.map((r) => {
        const last = r.points.at(-1);
        const v = last && step <= last[0] ? valueAt(r.points, step) : null;
        return `${r.seed != null ? `s${r.seed}` : r.run_id.slice(-4)} ${v == null ? "—" : fmtValue(v)}`;
      });
      const m = valueAt(cell.mean, step);
      // an own-axis row names its own step: it is not the header's step
      const label = own(name) ? `${name} (step ${step.toLocaleString("en-US")})` : name;
      lines.push(`${label}  ${parts.join("  ")}  mean ${m == null ? "—" : fmtValue(m)}`);
    }
    return lines.join("\n");
  };

  const move = (col: (typeof columns)[number], e: MouseEvent<SVGRectElement>): void => {
    const svg = e.currentTarget.closest("svg");
    const px = e.clientX - (svg ? svg.getBoundingClientRect().left : 0);
    if (model.names.every((n) => col.stepAt(n, px) == null)) return;
    setHover({ col: col.ci, px });
    onHover(tipText(col, px), e.clientX, e.clientY);
  };

  /**
   * The crosshair: one line through the column on the shared scale; with own-axis rows,
   * one segment per row, each at that row's step on that row's own x scale.
   */
  const crosshair = (col: (typeof columns)[number], px: number): ReactElement[] => {
    if (model.ownAxis.length === 0) {
      const step = col.stepAt(model.names[0] ?? "", px);
      if (step == null) return [];
      const xs = col.x.at(step);
      return [<line key="xh" className="xh" x1={xs} x2={xs} y1={TITLE_H - 4} y2={bottom} />];
    }
    return rows.flatMap((r) => {
      const step = col.stepAt(r.name, px);
      if (step == null) return [];
      const xs = col.xOf(r.name).at(step);
      return [<line key={r.name} className="xh" data-row={r.name} x1={xs} x2={xs} y1={r.top} y2={r.top + r.h} />];
    });
  };

  return (
    <svg
      className="hx-chart"
      width={width}
      height={H}
      role="img"
      aria-label={`${model.names.join(", ")} by step, one column per group`}
    >
      {rows.map((r) => (
        <text key={r.name} className="lbl" x={0} y={r.top + r.h / 2 + 4}>
          {r.name}
        </text>
      ))}
      {columns.map((col) => (
        <g key={col.g.group_id} className="curve-col" data-group={col.g.group_id}>
          <g>
            <title>{col.g.group_id}</title>
            <text className="ttl" x={col.x0} y={15}>
              {col.g.label}
            </text>
          </g>
          {rows.map((r, ri) => {
            const scale = model.scales[r.name] ?? { kind: "linear", domain: [0, 1] };
            const y = yScaleFor(scale, r.top, r.h);
            const cell = model.cells.get(cellKey(col.g.group_id, r.name));
            const clipId = `${uid}-c${col.ci}r${ri}`;
            const xr = col.xOf(r.name);
            const path = line<[number, number]>()
              .x((p) => xr.at(p[0]))
              .y((p) => y.at(p[1]));
            const dot = (pts: Array<[number, number]>) => (pts.length === 1 ? pts[0] : null);
            const lrRun = cell?.runs.reduce((a, b) => (b.points.length > a.points.length ? b : a));
            const lrPeak = lrRun ? Math.max(...lrRun.points.map((p) => p[1])) : 0;
            return (
              <g key={r.name} className="curve-cell" data-name={r.name}>
                {scale.kind === "lr" ? null : <GridY y={y.at} ticks={y.ticks} x0={col.x0} x1={col.x0 + colW} />}
                {col.ci === 0 && scale.kind !== "lr" ? (
                  <AxisLeftLabels y={y.at} ticks={y.ticks} x={gutter - 10} format={fmtValue} />
                ) : null}
                <line
                  className={ri === rows.length - 1 ? "axis" : "hair"}
                  x1={col.x0}
                  x2={col.x0 + colW}
                  y1={r.top + r.h}
                  y2={r.top + r.h}
                />
                <clipPath id={clipId}>
                  <rect x={col.x0 - 2} y={r.top - 3} width={colW + 4} height={r.h + 6} />
                </clipPath>
                <g clipPath={`url(#${clipId})`}>
                  {scale.kind === "lr" && lrRun ? (
                    <>
                      <path
                        className="lra"
                        d={
                          area<[number, number]>()
                            .x((p) => xr.at(p[0]))
                            .y0(y.at(0))
                            .y1((p) => y.at(p[1]))(lrRun.points) ?? ""
                        }
                      />
                      <path className="lrl" d={path(lrRun.points) ?? ""} />
                    </>
                  ) : (
                    <>
                      {cell?.runs.map((rs) => (
                        <path key={rs.run_id} className="sl" data-run={rs.run_id} d={path(rs.points) ?? ""} />
                      ))}
                      {cell ? <path className="ml" d={path(cell.mean) ?? ""} /> : null}
                      {cell && dot(cell.mean) ? (
                        <circle
                          className="md"
                          data-dot=""
                          cx={xr.at(dot(cell.mean)?.[0] ?? 0)}
                          cy={y.at(dot(cell.mean)?.[1] ?? 0)}
                          r={3}
                        />
                      ) : null}
                    </>
                  )}
                </g>
                {scale.kind === "lr" && lrRun ? (
                  <text className="lbl-s" x={col.x0 + colW} y={r.top + 10} textAnchor="end">
                    peak {fmtValue(lrPeak)}
                  </text>
                ) : null}
                {model.events
                  .filter((e) => col.runIds.has(e.run_id))
                  .map((e) => {
                    const rs = cell?.runs.find((x) => x.run_id === e.run_id);
                    if (e.kind === "spike" || e.kind === "nonfinite") {
                      // an own-axis row's steps stop at its own last step: a later NaN is not on it
                      if (own(r.name) && e.step > rowStepMax(r.name)) return null;
                      const nan = e.kind === "nonfinite";
                      const ex = xr.at(e.step);
                      const after = nan ? undefined : rs?.points.find((p) => p[0] >= e.step);
                      const vy = after ? y.at(after[1]) : null;
                      const text = nan ? `NaN ${kStep(e.step)}` : kStep(e.step);
                      return (
                        <g key={`${e.run_id}-${e.step}-${e.kind}`} className={`event ${e.kind}`}>
                          <title>{e.label ?? (nan ? text : `spike ${text}`)}</title>
                          <line className="ev" x1={ex} x2={ex} y1={r.top} y2={r.top + r.h} />
                          {ri === 0 ? (
                            <>
                              <SpikeMark x={ex - 16} y={r.top - 8} s={0.8} />
                              <text className="lbl-s" x={ex - 26} y={r.top - 4} textAnchor="end">
                                {text}
                              </text>
                            </>
                          ) : null}
                          {scale.kind !== "lr" && after && vy != null && vy < r.top ? (
                            <Caret x={ex} y={r.top} up v={after[1]} />
                          ) : null}
                          {scale.kind !== "lr" && after && vy != null && vy > r.top + r.h ? (
                            <Caret x={ex} y={r.top + r.h} up={false} v={after[1]} />
                          ) : null}
                        </g>
                      );
                    }
                    const last = rs?.points.at(-1);
                    if (scale.kind === "lr" || !last) return null;
                    const ky = Math.max(r.top, Math.min(r.top + r.h, y.at(last[1])));
                    return (
                      <g key={`${e.run_id}-${e.kind}`} className={`event ${e.kind}`}>
                        <title>{e.label ?? `${e.kind} ${kStep(e.step)}`}</title>
                        <KillMark x={xr.at(last[0])} y={ky} />
                      </g>
                    );
                  })}
                {model.checkpoints
                  .filter((c) => c.name === r.name && c.group_id === col.g.group_id)
                  .map((c) => (
                    <CheckpointMark key={`${c.run_id}-${c.step}`} cx={xr.at(c.step)} cy={y.at(c.value)} best />
                  ))}
                {r.axis ? (
                  <AxisBottom
                    x={xr.at}
                    ticks={xr.ticks}
                    y={r.top + r.h}
                    x0={col.x0}
                    x1={col.x0 + colW}
                    format={kStep}
                  />
                ) : null}
              </g>
            );
          })}
          {(() => {
            const lastName = model.names.at(-1) ?? "";
            const xl = col.xOf(lastName);
            return (
              <AxisBottom
                x={xl.at}
                ticks={own(lastName) ? xl.ticks : xTicks}
                y={bottom}
                x0={col.x0}
                x1={col.x0 + colW}
                format={kStep}
              />
            );
          })()}
          {hover?.col === col.ci ? crosshair(col, hover.px) : null}
          <rect
            className="hit"
            data-hit={col.g.group_id}
            x={col.x0}
            y={TITLE_H - 4}
            width={colW}
            height={bottom - TITLE_H + 4}
            style={{ cursor: "crosshair" }}
            onMouseMove={(e) => move(col, e)}
            onMouseLeave={() => {
              setHover(null);
              onHover(null, 0, 0);
            }}
          />
        </g>
      ))}
    </svg>
  );
}

/** One value of {@link CurvesModel.values}: a metric's single point in one group. */
export interface ValueStat {
  name: string;
  group_id: string;
  /** `name`, plus the group's title when the panel has more than one group. */
  label: string;
  /** Mean over the group's runs. */
  value: number;
  /** Each run's value, `s1 0.8  s2 0.9` (seed, else the run id's last 4 characters). */
  title: string;
}

/**
 * The values to show for `model.values`, one per metric and group with points, in metric
 * then group order.
 *
 * Examples
 * --------
 * >>> valueStats(buildCurves([{ run_id: "r", group_id: "g", seed: 1, name: "acc", step: 0, value: 0.9 }], {}))
 * [{ name: "acc", group_id: "g", label: "acc", value: 0.9, title: "s1 0.9" }]
 */
export function valueStats(model: CurvesModel): ValueStat[] {
  const several = model.groups.length > 1;
  return model.values.flatMap((name) =>
    model.groups.flatMap((g) => {
      const cell = model.cells.get(cellKey(g.group_id, name));
      const point = cell?.mean[0];
      if (!cell || !point) return [];
      const runs = cell.runs.map((r) => {
        const v = r.points[0]?.[1];
        return `${r.seed != null ? `s${r.seed}` : r.run_id.slice(-4)} ${v == null ? "—" : fmtValue(v)}`;
      });
      return [
        { name, group_id: g.group_id, label: several ? `${name} ${g.label}` : name, value: point[1], title: runs.join("  ") },
      ];
    }),
  );
}

/** Draw a `curves` panel result. */
export function Curves({ result }: PanelProps): ReactElement {
  const [ref, width] = useElementWidth<HTMLDivElement>(960);
  const tip = useTooltip();
  const model = useMemo(
    () => buildCurves(result.rows as unknown as CurvePoint[], result.meta),
    [result.rows, result.meta],
  );
  if (model.names.length === 0 && model.values.length === 0) {
    return (
      <div ref={ref}>
        <p className="panel-empty">No metric history yet</p>
      </div>
    );
  }
  const stats = valueStats(model);
  const statStrip =
    stats.length > 0 ? (
      <dl className="stats">
        {stats.map((st) => (
          <div key={`${st.name}\u0000${st.group_id}`} title={st.title}>
            <dt>{st.label}</dt>
            <dd>{fmtValue(st.value)}</dd>
          </div>
        ))}
      </dl>
    ) : null;
  if (model.names.length === 0) {
    return (
      <div className="curves" ref={ref}>
        {statStrip}
      </div>
    );
  }
  // columns only for groups with a curve; a group with only values is in the strip
  const curveGroups = model.groups.filter((g) => model.names.some((n) => model.cells.has(cellKey(g.group_id, n))));
  const cols = Math.min(MAX_COLS, curveGroups.length);
  const bands: GroupJson[][] = [];
  for (let i = 0; i < curveGroups.length; i += MAX_COLS) bands.push(curveGroups.slice(i, i + MAX_COLS));
  const onHover = (text: string | null, x: number, y: number): void => {
    if (text) tip.show(text, x, y);
    else tip.hide();
  };
  const keyItems: KeyItem[] = [
    { glyph: "seedLine", label: "seed" },
    { glyph: "meanLine", label: "mean" },
  ];
  if (model.checkpoints.length) keyItems.push({ glyph: "bestCkpt", label: "best ckpt" });
  if (model.events.some((e) => e.kind === "spike")) {
    keyItems.push({ glyph: "spike", label: "spike", title: "Loss above 5× the median of the previous 20 points" });
  }
  if (model.events.some((e) => e.kind === "nonfinite")) {
    keyItems.push({ glyph: "spike", label: "NaN", title: "A NaN or infinite value was logged" });
  }
  if (model.events.some((e) => e.kind === "killed" || e.kind === "failed")) {
    keyItems.push({ glyph: "killed", label: "killed" });
  }
  return (
    <div className="curves" ref={ref}>
      {statStrip}
      {bands.map((groups) => (
        <CurveStack
          key={groups.map((g) => g.group_id).join("|")}
          model={model}
          groups={groups}
          width={width}
          cols={cols}
          onHover={onHover}
        />
      ))}
      <Key items={keyItems} />
      {tip.node}
    </div>
  );
}
