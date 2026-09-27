/**
 * `curves` panel: small multiples of metric histories.
 *
 * One column per seed group, one row per metric, all on one step axis. Seeds are
 * faint lines, the seed mean is bold. The best checkpoint of each run is a green
 * dot; loss spikes are dashed red lines with a spike glyph, killed or failed runs
 * end in a red cross. Values pushed off the panel by a spike get a red caret with
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
  kind: "spike" | "killed" | "failed";
}

/** `meta.groups[]`. */
export interface GroupJson {
  group_id: string;
  label: string;
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
  groups: GroupJson[];
  names: string[];
  cells: Map<string, Cell>;
  maxStep: number;
  scales: Record<string, RowScale>;
  checkpoints: PlacedCheckpoint[];
  events: Array<EventJson & { group_id: string }>;
}

/** Most columns per band of small multiples. */
export const MAX_COLS = 3;
/** Width of the row-label gutter. */
export const LABEL_W = 104;
/** Gap between columns. */
export const COL_GAP = 36;
/** Height of the column-title strip. */
export const TITLE_H = 34;
/** Height of a metric row, and of the learning-rate row. */
export const ROW_H = 116;
export const LR_ROW_H = 40;
/** Gap between metric rows. */
export const ROW_GAP = 16;
/** Share of the step axis after a spike that is left out of the y-domain. */
export const SPIKE_WINDOW = 0.1;

/** True for learning-rate metric names (`lr`, `learning_rate`, `train/lr`). */
export function isLr(name: string): boolean {
  return /(^|[/_.])lr$|learning_rate$/.test(name);
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
 *     Groups in `meta.groups` order (unknown groups appended), metric names in
 *     first-seen order with learning-rate rows last, and per-row scales. Points of a
 *     spiked run within {@link SPIKE_WINDOW} of the axis after the spike are left
 *     out of the y-domain so one spike does not flatten every other line.
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
  let maxStep = 0;
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
    maxStep = Math.max(maxStep, p.step);
  }
  names.sort((a, b) => Number(isLr(a)) - Number(isLr(b)));

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
  const window = SPIKE_WINDOW * maxStep;
  const scales: Record<string, RowScale> = {};
  for (const name of names) {
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
  return {
    groups,
    names,
    cells,
    maxStep,
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
}

function rowGeometry(names: string[]): { rows: RowGeom[]; bottom: number } {
  let y = TITLE_H;
  const rows = names.map((name) => {
    const h = isLr(name) ? LR_ROW_H : ROW_H;
    const r = { name, top: y, h };
    y += h + ROW_GAP;
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
  const [hover, setHover] = useState<{ col: number; step: number } | null>(null);
  const colW = Math.max(40, (width - LABEL_W - COL_GAP * (cols - 1)) / cols);
  const { rows, bottom } = rowGeometry(model.names);
  const H = bottom + 30;
  const xTicks = linear([0, model.maxStep || 1], 0, 1, 4).ticks;

  const columns = groups.map((g, ci) => {
    const x0 = LABEL_W + ci * (colW + COL_GAP);
    const x = linear([0, model.maxStep || 1], x0, x0 + colW, 4);
    const runIds = new Set(
      model.names.flatMap((n) => model.cells.get(cellKey(g.group_id, n))?.runs.map((r) => r.run_id) ?? []),
    );
    const steps = [
      ...new Set(
        model.names.flatMap((n) => model.cells.get(cellKey(g.group_id, n))?.mean.map((p) => p[0]) ?? []),
      ),
    ].sort((a, b) => a - b);
    return { g, ci, x0, x, runIds, steps };
  });

  const tipText = (col: (typeof columns)[number], step: number): string => {
    const lines = [`${col.g.label}, step ${step.toLocaleString("en-US")}`];
    for (const name of model.names) {
      const cell = model.cells.get(cellKey(col.g.group_id, name));
      if (!cell) continue;
      const parts = cell.runs.map((r) => {
        const last = r.points.at(-1);
        const v = last && step <= last[0] ? valueAt(r.points, step) : null;
        return `${r.seed != null ? `s${r.seed}` : r.run_id.slice(-4)} ${v == null ? "—" : fmtValue(v)}`;
      });
      const m = valueAt(cell.mean, step);
      lines.push(`${name}  ${parts.join("  ")}  mean ${m == null ? "—" : fmtValue(m)}`);
    }
    return lines.join("\n");
  };

  const move = (col: (typeof columns)[number], e: MouseEvent<SVGRectElement>): void => {
    const svg = e.currentTarget.closest("svg");
    const left = svg ? svg.getBoundingClientRect().left : 0;
    const raw = col.x.invert(e.clientX - left);
    const step = col.steps[bisectCenter(col.steps, raw)];
    if (step == null) return;
    setHover({ col: col.ci, step });
    onHover(tipText(col, step), e.clientX, e.clientY);
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
          <text className="ttl" x={col.x0} y={15}>
            {col.g.label}
          </text>
          {rows.map((r, ri) => {
            const scale = model.scales[r.name] ?? { kind: "linear", domain: [0, 1] };
            const y = yScaleFor(scale, r.top, r.h);
            const cell = model.cells.get(cellKey(col.g.group_id, r.name));
            const clipId = `${uid}-c${col.ci}r${ri}`;
            const path = line<[number, number]>()
              .x((p) => col.x.at(p[0]))
              .y((p) => y.at(p[1]));
            const lrRun = cell?.runs.reduce((a, b) => (b.points.length > a.points.length ? b : a));
            const lrPeak = lrRun ? Math.max(...lrRun.points.map((p) => p[1])) : 0;
            return (
              <g key={r.name} className="curve-cell" data-name={r.name}>
                {scale.kind === "lr" ? null : <GridY y={y.at} ticks={y.ticks} x0={col.x0} x1={col.x0 + colW} />}
                {col.ci === 0 && scale.kind !== "lr" ? (
                  <AxisLeftLabels y={y.at} ticks={y.ticks} x={LABEL_W - 10} format={fmtValue} />
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
                            .x((p) => col.x.at(p[0]))
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
                    if (e.kind === "spike") {
                      const ex = col.x.at(e.step);
                      const after = rs?.points.find((p) => p[0] >= e.step);
                      const vy = after ? y.at(after[1]) : null;
                      return (
                        <g key={`${e.run_id}-${e.step}-${e.kind}`} className="event spike">
                          <line className="ev" x1={ex} x2={ex} y1={r.top} y2={r.top + r.h} />
                          {ri === 0 ? (
                            <>
                              <SpikeMark x={ex - 16} y={r.top - 8} s={0.8} />
                              <text className="lbl-s" x={ex - 26} y={r.top - 4} textAnchor="end">
                                {kStep(e.step)}
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
                    return <KillMark key={`${e.run_id}-${e.kind}`} x={col.x.at(last[0])} y={ky} />;
                  })}
                {model.checkpoints
                  .filter((c) => c.name === r.name && c.group_id === col.g.group_id)
                  .map((c) => (
                    <CheckpointMark key={`${c.run_id}-${c.step}`} cx={col.x.at(c.step)} cy={y.at(c.value)} best />
                  ))}
              </g>
            );
          })}
          <AxisBottom x={col.x.at} ticks={xTicks} y={bottom} x0={col.x0} x1={col.x0 + colW} format={kStep} />
          {hover?.col === col.ci ? (
            <line className="xh" x1={col.x.at(hover.step)} x2={col.x.at(hover.step)} y1={TITLE_H - 4} y2={bottom} />
          ) : null}
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

/** Draw a `curves` panel result. */
export function Curves({ result }: PanelProps): ReactElement {
  const [ref, width] = useElementWidth<HTMLDivElement>(960);
  const tip = useTooltip();
  const model = useMemo(
    () => buildCurves(result.rows as unknown as CurvePoint[], result.meta),
    [result.rows, result.meta],
  );
  if (model.names.length === 0) {
    return (
      <div ref={ref}>
        <p className="panel-empty">No metric history yet</p>
      </div>
    );
  }
  const cols = Math.min(MAX_COLS, model.groups.length);
  const bands: GroupJson[][] = [];
  for (let i = 0; i < model.groups.length; i += MAX_COLS) bands.push(model.groups.slice(i, i + MAX_COLS));
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
  if (model.events.some((e) => e.kind !== "spike")) keyItems.push({ glyph: "killed", label: "killed" });
  return (
    <div className="curves" ref={ref}>
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
