/**
 * Step-metric line chart (spec 4.2 "Step metrics"), ported from the v5 mockup's
 * `lineChart`: nice ticks, EMA smoothing with the raw line faint, NaN gaps, a × at a failed
 * run's last point, a dot at a running run's head, and a crosshair shared by every chart of
 * one `crosshairGroup` with one marker per series and one tooltip. The x axis reads steps
 * (from 0), wall-clock epoch seconds (`xAxis="clock"`, the data's own extent) or seconds
 * since a start (`xAxis="duration"`, from 0).
 */
import { type MouseEvent, type ReactElement, useId, useMemo } from "react";

import { niceTicks, tickFormatter } from "../lib/ticks";
import { useChartLabel } from "./chartLabel";
import { useCrosshair } from "./crosshair";
import { fmtValue, kStep } from "./Scale";
import { type XAxisKind, fmtClock, fmtClockTip, fmtSpan, localOffset, timeTicks } from "./timeAxis";
import { type TipRow, hideTip, showTip } from "./Tooltip";
import "./charts.css";

/** `[x, y]`; points are sorted by x; a non-finite y is a gap. */
export type Point = readonly [x: number, y: number];

/** `[x, lo, hi]` of a seeds band; sorted by x; a non-finite lo or hi is a gap. */
export type Band = readonly [x: number, lo: number, hi: number];

export interface LineSeries {
  id: string;
  /** Config group of the run; `highlight` matches it too. */
  groupId?: string;
  name: string;
  /** Identity colour, e.g. `colorFor(id, visible)`. */
  color: string;
  points: readonly Point[];
  /** Seeds band ("mean + band"), drawn as a faint area behind the line. */
  band?: readonly Band[];
  bold?: boolean;
  faint?: boolean;
  running?: boolean;
  failed?: boolean;
  /** Hidden in the run list: not drawn, not in the axis range or the tooltip. */
  hidden?: boolean;
}

export interface LineChartProps {
  series: readonly LineSeries[];
  width: number;
  height?: number;
  /** EMA weight of the previous value, 0 (raw) to 0.99. */
  smoothing?: number;
  yFormat?: (v: number) => string;
  /** What x is: "step" (default), "clock" (epoch seconds) or "duration" (seconds). */
  xAxis?: XAxisKind;
  /** Overrides the x tick labels and the tooltip's x. */
  xFormat?: (v: number) => string;
  /** Word before the hovered x in the tooltip, e.g. "step" or "s". */
  xLabel?: string;
  /** Charts with the same group share the hovered x. */
  crosshairGroup?: string;
  /** Series id or group id to emphasise (run-list hover); the others are dimmed. */
  highlight?: string | null;
}

export const LINE_MARGIN = { l: 44, r: 10, t: 8, b: 22 } as const;
export const MAX_TIP_ROWS = 8;

const r1 = (v: number): number => Math.round(v * 10) / 10;
const finite = (p: Point): boolean => Number.isFinite(p[0]) && Number.isFinite(p[1]);

/** Exponential moving average; gaps stay gaps and do not reset the average. */
export function ema(points: readonly Point[], alpha: number): Point[] {
  if (!(alpha > 0)) return points.slice();
  let last: number | null = null;
  return points.map(([x, y]): Point => {
    if (!Number.isFinite(y)) return [x, y];
    last = last === null ? y : last * alpha + y * (1 - alpha);
    return [x, last];
  });
}

/** SVG path through the finite points; a gap starts a new `M` segment. */
export function linePath(points: readonly Point[], X: (v: number) => number, Y: (v: number) => number): string {
  let d = "";
  let pen = false;
  for (const p of points) {
    if (!finite(p)) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${r1(X(p[0]))},${r1(Y(p[1]))}`;
    pen = true;
  }
  return d;
}

/** Closed area paths of a band: along `hi`, back along `lo`; a gap starts a new area. */
export function bandPath(band: readonly Band[], X: (v: number) => number, Y: (v: number) => number): string {
  let d = "";
  let run: Band[] = [];
  const flush = (): void => {
    if (run.length >= 2) {
      const top = run.map(([x, , hi], i) => `${i === 0 ? "M" : "L"}${r1(X(x))},${r1(Y(hi))}`).join("");
      const bottom = [...run].reverse().map(([x, lo]) => `L${r1(X(x))},${r1(Y(lo))}`).join("");
      d += `${top}${bottom}Z`;
    }
    run = [];
  };
  for (const b of band) {
    if (Number.isFinite(b[0]) && Number.isFinite(b[1]) && Number.isFinite(b[2])) run.push(b);
    else flush();
  }
  flush();
  return d;
}

/** The point with the x nearest to `x`, or null when `x` is outside the points' range. */
export function pointAt(points: readonly Point[], x: number): Point | null {
  const n = points.length;
  if (n === 0) return null;
  const first = points[0];
  const last = points[n - 1];
  if (!first || !last || x < first[0] || x > last[0]) return null;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((points[mid]?.[0] ?? 0) <= x) lo = mid;
    else hi = mid;
  }
  const a = points[lo];
  const b = points[hi];
  if (!a || !b) return null;
  return x - a[0] <= b[0] - x ? a : b;
}

/** The value in sorted `xs` nearest to `x`, or null for no values. */
export function nearestX(xs: readonly number[], x: number): number | null {
  if (xs.length === 0) return null;
  let lo = 0;
  let hi = xs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((xs[mid] ?? 0) <= x) lo = mid;
    else hi = mid;
  }
  const a = xs[lo] ?? 0;
  const b = xs[hi] ?? 0;
  return Math.abs(x - a) <= Math.abs(b - x) ? a : b;
}

/** Tooltip rows at `x`: every series with a point there, high values first, at most 8. */
export function tipRows(
  lines: readonly { series: LineSeries; points: readonly Point[] }[],
  x: number,
  format: (v: number) => string,
): TipRow[] {
  const rows: { v: number; row: TipRow }[] = [];
  for (const { series, points } of lines) {
    const p = pointAt(points, x);
    if (p) rows.push({ v: p[1], row: { color: series.color, value: format(p[1]), name: series.name } });
  }
  return rows
    .sort((a, b) => b.v - a.v)
    .slice(0, MAX_TIP_ROWS)
    .map((r) => r.row);
}

interface Line {
  series: LineSeries;
  smooth: Point[];
  /** Finite smoothed points: markers, tooltip and end glyphs read these. */
  done: Point[];
}

export function LineChart({
  series,
  width,
  height = 190,
  smoothing = 0,
  yFormat,
  xAxis = "step",
  xFormat,
  xLabel = "step",
  crosshairGroup,
  highlight = null,
}: LineChartProps): ReactElement {
  const localGroup = useId();
  const label = useChartLabel("Line chart");
  const [hoverX, setHoverX] = useCrosshair(crosshairGroup ?? localGroup);
  const alpha = Math.min(Math.max(smoothing, 0), 0.99);
  const m = LINE_MARGIN;
  const pw = Math.max(1, width - m.l - m.r);
  const ph = Math.max(1, height - m.t - m.b);

  const geo = useMemo(() => {
    const lines: Line[] = series
      .filter((s) => !s.hidden)
      .map((s) => {
        const smooth = ema(s.points, alpha);
        return { series: s, smooth, done: smooth.filter(finite) };
      });
    let xMin = Number.POSITIVE_INFINITY;
    let xMax = Number.NEGATIVE_INFINITY;
    let yMin = Number.POSITIVE_INFINITY;
    let yMax = Number.NEGATIVE_INFINITY;
    for (const { series: s } of lines) {
      for (const p of s.points) {
        if (!finite(p)) continue;
        xMin = Math.min(xMin, p[0]);
        xMax = Math.max(xMax, p[0]);
        yMin = Math.min(yMin, p[1]);
        yMax = Math.max(yMax, p[1]);
      }
      for (const [x, lo, hi] of s.band ?? []) {
        if (!Number.isFinite(x) || !Number.isFinite(lo) || !Number.isFinite(hi)) continue;
        yMin = Math.min(yMin, lo);
        yMax = Math.max(yMax, hi);
      }
    }
    if (!Number.isFinite(yMin)) return null;
    const pad = (yMax - yMin) * 0.06 || Math.abs(yMax) * 0.05 || 1;
    const y0 = yMin - pad;
    const y1 = yMax + pad;
    // steps and durations start at 0; a wall clock spans the data only
    const x0 = xAxis === "clock" ? xMin : Math.min(0, xMin);
    const x1 = xMax > x0 ? xMax : x0 + 1;
    const yTicks = niceTicks(y0, y1, height >= 160 ? 5 : 4);
    const xCount = width > 500 ? 6 : 4;
    const xTicks =
      xAxis === "step" ? niceTicks(x0, x1, xCount) : timeTicks(x0, x1, xCount, xAxis === "clock" ? localOffset(x0) : 0);
    const xStep = xTicks.length > 1 ? (xTicks[1] ?? 0) - (xTicks[0] ?? 0) : x1 - x0;
    const xs = [...new Set(lines.flatMap((l) => l.done.map((p) => p[0])))].sort((a, b) => a - b);
    return { lines, x0, x1, y0, y1, yTicks, xTicks, xStep, xs };
  }, [series, alpha, height, width, xAxis]);

  if (!geo) {
    return (
      <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="No data">
        <text className="none" x={width / 2} y={height / 2} textAnchor="middle">
          no data
        </text>
      </svg>
    );
  }

  const X = (v: number): number => m.l + ((v - geo.x0) / (geo.x1 - geo.x0)) * pw;
  const Y = (v: number): number => m.t + (1 - (v - geo.y0) / (geo.y1 - geo.y0)) * ph;
  const yTick = yFormat ?? tickFormatter(geo.yTicks);
  const yValue = yFormat ?? fmtValue;
  const xTick =
    xFormat ??
    (xAxis === "clock" ? (v: number) => fmtClock(v, geo.xStep) : xAxis === "duration" ? fmtSpan : kStep);
  const xTip =
    xFormat ??
    (xAxis === "clock"
      ? (v: number) => fmtClockTip(v, geo.xStep)
      : xAxis === "duration"
        ? fmtSpan
        : (v: number) => v.toLocaleString("en-US"));
  const xAnchor = (px: number): "start" | "middle" | "end" =>
    px < m.l + 12 ? "start" : px > width - m.r - 12 ? "end" : "middle";
  const dimClass = (s: LineSeries): string =>
    highlight === null ? "" : s.id === highlight || s.groupId === highlight ? " hi" : " dim";

  const onMove = (e: MouseEvent<SVGRectElement>): void => {
    const left = e.currentTarget.closest("svg")?.getBoundingClientRect().left ?? 0;
    const data = geo.x0 + ((e.clientX - left - m.l) / pw) * (geo.x1 - geo.x0);
    const x = nearestX(geo.xs, data);
    if (x === null) return;
    setHoverX(x);
    const rows = tipRows(
      geo.lines.map((l) => ({ series: l.series, points: l.done })),
      x,
      yValue,
    );
    showTip(e.clientX, e.clientY, `${xLabel} ${xTip(x)}`, rows);
  };
  const onLeave = (): void => {
    setHoverX(null);
    hideTip();
  };

  const showCross = hoverX !== null && hoverX >= geo.x0 && hoverX <= geo.x1;

  return (
    <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      {geo.yTicks.map((v) => (
        <g key={`y${v}`}>
          <line className="gl" x1={m.l} x2={width - m.r} y1={r1(Y(v))} y2={r1(Y(v))} />
          <text className="yt" x={m.l - 6} y={r1(Y(v) + 3.5)} textAnchor="end">
            {yTick(v)}
          </text>
        </g>
      ))}
      {geo.xTicks.map((v) => (
        <text key={`x${v}`} className="xt" x={r1(X(v))} y={height - 6} textAnchor={xAnchor(X(v))}>
          {xTick(v)}
        </text>
      ))}
      <line className="ax" x1={m.l} x2={width - m.r} y1={height - m.b} y2={height - m.b} />
      {geo.lines.map(({ series: s, smooth, done }) => (
        <g key={s.id} data-id={s.id} data-series={s.groupId ?? s.id}>
          {s.band && s.band.length > 0
            ? bandPath(s.band, X, Y)
                .split("Z")
                .filter(Boolean)
                .map((d, i) => (
                  <path key={`band${i}`} className={`sarea${dimClass(s) === " dim" ? " dim" : ""}`} d={`${d}Z`} fill={s.color} />
                ))
            : null}
          {alpha > 0 ? <path className={`ln raw${dimClass(s)}`} d={linePath(s.points, X, Y)} stroke={s.color} /> : null}
          <path
            className={`ln${s.bold ? " bold" : ""}${s.faint ? " faint" : ""}${dimClass(s)}`}
            d={linePath(smooth, X, Y)}
            stroke={s.color}
          />
          {/* one logged point: a one-point path draws nothing, so mark it (the end marks cover running and failed) */}
          {done.length === 1 && done[0] && !s.failed && !s.running ? (
            <circle className={`mk${dimClass(s)}`} cx={r1(X(done[0][0]))} cy={r1(Y(done[0][1]))} r={3.5} fill={s.color} />
          ) : null}
        </g>
      ))}
      {geo.lines.map(({ series: s, done }) => {
        const last = done[done.length - 1];
        if (!last) return null;
        const px = r1(X(last[0]));
        const py = r1(Y(last[1]));
        if (s.failed) return <path key={`end-${s.id}`} className="fail-x" d={`M${r1(px - 3.5)} ${r1(py - 3.5)}l7 7m0-7l-7 7`} />;
        if (s.running) return <circle key={`end-${s.id}`} className="live" cx={px} cy={py} r={3} fill={s.color} />;
        return null;
      })}
      {showCross ? (
        <g>
          <line className="xh" x1={r1(X(hoverX))} x2={r1(X(hoverX))} y1={m.t} y2={height - m.b} />
          {geo.lines.map(({ series: s, done }) => {
            const p = pointAt(done, hoverX);
            return p ? <circle key={`mk-${s.id}`} className="mk" cx={r1(X(p[0]))} cy={r1(Y(p[1]))} r={3.5} fill={s.color} /> : null;
          })}
        </g>
      ) : null}
      <rect className="hit" x={m.l} y={0} width={pw} height={height} onMouseMove={onMove} onMouseLeave={onLeave} />
    </svg>
  );
}
