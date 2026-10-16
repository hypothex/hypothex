/**
 * Step metrics (spec 4.2, 4.3): which logged metrics are drawn over time, and their
 * sections by the first `/` prefix. The Task and Run Charts tabs share these helpers so
 * both show the same metric set. For the Task Charts tab also the `views/query` body that
 * reads the visible runs' histories (curves panels, `group_by: group`, at most 100 metrics
 * per panel) and the series one LineChart draws.
 *
 * Seeds: `mean` is the mean over a config's runs on the union of their steps (each run
 * linearly interpolated inside its own step range, so runs thinned at different steps
 * still average); `band` adds the min..max over runs as a faint area (`LineSeries.band`);
 * `each` draws every run in the identity's colour with `groupId` = the identity, so the
 * sidebar hover highlights all of them. Series ids are unique (`LineChart` keys by id); the
 * identity's main line has the identity id.
 */
import type { PanelSpec, TaskRun, ViewQueryBody } from "../api/models";
import type { Band, LineSeries, Point } from "../charts/LineChart";
import type { XAxisKind } from "../charts/timeAxis";
import { SWEEP_PREFIX } from "../pages/components/KindPanels";
import { type Identity, runLabel } from "./useRunSelection";

export type SeedsMode = "mean" | "band" | "each";
export type XMode = "step" | "wall" | "relative";
export const X_LABEL: Record<XMode, string> = { step: "step", wall: "wall time", relative: "relative time" };
/** How the line chart reads each x mode: steps, wall-clock epoch seconds, seconds since start. */
export const X_AXIS: Record<XMode, XAxisKind> = { step: "step", wall: "clock", relative: "duration" };
export const CURVE_POINTS = 300;
export const METRICS_PER_PANEL = 100;

/** A `curves` row; `t` (wall-clock seconds) when the server sends it. */
export interface CurvePoint {
  run_id: string;
  group_id: string;
  seed: number | null;
  name: string;
  step: number;
  value: number;
  t?: number | null;
}

export interface MetricSection {
  title: string;
  metrics: string[];
}

/** Metrics over time: `sweep/*` (step = the swept value) and the step counter are left out. */
export function stepMetrics(names: readonly string[]): string[] {
  return names.filter((n) => !n.startsWith(SWEEP_PREFIX) && n !== "step");
}

/** One section per first `/` prefix, first-seen order; names without a prefix go to "metrics". */
export function metricSections(names: readonly string[]): MetricSection[] {
  const out = new Map<string, string[]>();
  for (const name of names) {
    const cut = name.indexOf("/");
    const title = cut > 0 ? name.slice(0, cut) : "metrics";
    out.set(title, [...(out.get(title) ?? []), name]);
  }
  return [...out].map(([title, metrics]) => ({ title, metrics }));
}

/** Panel search: a case-insensitive substring of the title; a blank query matches all. */
export function matchesSearch(title: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  return q === "" || title.toLowerCase().includes(q);
}

/** The `views/query` body for the histories of `names` over `runIds`; null when either is empty. */
export function stepCurvesBody(names: readonly string[], runIds: readonly string[]): ViewQueryBody | null {
  if (names.length === 0 || runIds.length === 0) return null;
  const panels: PanelSpec[] = [];
  for (let i = 0; i < names.length; i += METRICS_PER_PANEL) {
    panels.push({
      type: "curves",
      title: `step metrics ${panels.length + 1}`,
      data: {
        metrics: names.slice(i, i + METRICS_PER_PANEL),
        group_by: "group",
        max_points: CURVE_POINTS,
        filter: { run_id: [...runIds] },
      },
    });
  }
  return { view: { title: "Step metrics", panels } };
}

/** The x of a point: its step, its wall time, or its time since the run's first point (`start`). */
export function xOf(p: CurvePoint, mode: XMode, start: number | undefined): number | null {
  if (mode === "step") return p.step;
  if (typeof p.t !== "number") return null;
  if (mode === "wall") return p.t;
  return start === undefined ? null : p.t - start;
}

/** Any point carries a wall time (the time x axes are enabled). */
export function hasTime(points: readonly CurvePoint[]): boolean {
  return points.some((p) => typeof p.t === "number");
}

/** Linear interpolation inside the run's own range; null outside it. `list` is sorted by x. */
function valueAt(list: readonly Point[], x: number): number | null {
  const first = list[0];
  const last = list[list.length - 1];
  if (!first || !last || x < first[0] || x > last[0]) return null;
  let lo = 0;
  let hi = list.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((list[mid] as Point)[0] <= x) lo = mid;
    else hi = mid;
  }
  const [x0, y0] = list[lo] as Point;
  const [x1, y1] = list[hi] as Point;
  if (x === x0 || x1 === x0) return y0;
  if (x === x1) return y1;
  return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
}

const runState = (run: TaskRun): Pick<LineSeries, "running" | "failed"> => ({
  running: run.status === "running",
  failed: run.status === "failed",
});

/** The lines of one metric's panel: one per visible identity (or per seed in `each`). */
export function curveSeries(
  points: readonly CurvePoint[],
  metric: string,
  items: readonly Identity[],
  colorOf: (id: string) => string,
  seeds: SeedsMode,
  x: XMode,
): LineSeries[] {
  const start = new Map<string, number>();
  for (const p of points) if (typeof p.t === "number") start.set(p.run_id, Math.min(start.get(p.run_id) ?? Number.POSITIVE_INFINITY, p.t));
  const byRun = new Map<string, Point[]>();
  for (const p of points) {
    if (p.name !== metric || !Number.isFinite(p.value)) continue;
    const xv = xOf(p, x, start.get(p.run_id));
    if (xv === null) continue;
    const list = byRun.get(p.run_id);
    if (list) list.push([xv, p.value]);
    else byRun.set(p.run_id, [[xv, p.value]]);
  }
  for (const list of byRun.values()) list.sort((a, b) => a[0] - b[0]);
  const out: LineSeries[] = [];
  for (const item of items) {
    const color = colorOf(item.id);
    const own = item.runs.filter((r) => byRun.has(r.run_id));
    if (own.length === 0) continue;
    if (item.kind === "run" || own.length === 1) {
      const run = own[0] as TaskRun;
      out.push({ id: item.id, name: item.name, color, points: byRun.get(run.run_id) ?? [], ...runState(run) });
      continue;
    }
    if (seeds === "each") {
      for (const run of own) {
        out.push({ id: `${item.id}:${run.run_id}`, groupId: item.id, name: runLabel(run), color, points: byRun.get(run.run_id) ?? [], ...runState(run) });
      }
      continue;
    }
    const xs = [...new Set(own.flatMap((r) => (byRun.get(r.run_id) ?? []).map((p) => p[0])))].sort((a, b) => a - b);
    const mean: Point[] = [];
    const band: Band[] = [];
    for (const xv of xs) {
      const vs = own.map((r) => valueAt(byRun.get(r.run_id) ?? [], xv)).filter((v): v is number => v !== null);
      if (vs.length === 0) continue;
      mean.push([xv, vs.reduce((a, b) => a + b, 0) / vs.length]);
      if (vs.length > 1) band.push([xv, Math.min(...vs), Math.max(...vs)]);
    }
    out.push({
      id: item.id,
      name: item.name,
      color,
      points: mean,
      ...(seeds === "band" && band.length > 0 ? { band } : {}),
      running: own.some((r) => r.status === "running"),
      failed: own.every((r) => r.status === "failed"),
    });
  }
  return out;
}
