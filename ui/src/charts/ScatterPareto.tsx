/**
 * Score vs cost (spec 4.2 "Scores", training kinds), ported from the mockup's
 * `scatterChart`: one dot per config with its interval, x from zero, and the Pareto front
 * (lowest cost for the best score) as a dashed step line.
 */
import { type MouseEvent, type ReactElement } from "react";

import { niceExtent, niceTicks, tickFormatter } from "../lib/ticks";
import { fmtValue } from "./Scale";
import { hideTip, showTip } from "./Tooltip";
import "./charts.css";

export interface ScatterPoint {
  id: string;
  name: string;
  color: string;
  x: number;
  y: number;
  yLo?: number | null;
  yHi?: number | null;
}

export interface ScatterParetoProps {
  points: readonly ScatterPoint[];
  width: number;
  height?: number;
  xName?: string;
  yName?: string;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  higherIsBetter?: boolean;
}

const M = { l: 44, r: 12, t: 10, b: 22 } as const;
const isNum = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

/**
 * Points on the Pareto front, cheapest first: sorted by x, a point is kept when its y
 * beats every cheaper point (ties on x keep only the best y).
 *
 * Examples
 * --------
 * >>> paretoFront([{x: 1, y: 0.8}, {x: 2, y: 0.9}, {x: 3, y: 0.85}]).map((q) => q.x)
 * [1, 2]
 */
export function paretoFront(points: readonly ScatterPoint[], higherIsBetter = true): ScatterPoint[] {
  const better = (a: number, b: number): boolean => (higherIsBetter ? a > b : a < b);
  const sorted = points
    .filter((q) => isNum(q.x) && isNum(q.y))
    .sort((a, b) => a.x - b.x || (higherIsBetter ? b.y - a.y : a.y - b.y));
  const front: ScatterPoint[] = [];
  for (const q of sorted) {
    const last = front[front.length - 1];
    if (!last || better(q.y, last.y)) front.push(q);
  }
  return front;
}

/** Score (y, over the intervals) vs cost (x, from zero) with the Pareto front dashed. */
export function ScatterPareto({
  points,
  width,
  height,
  xName = "x",
  yName = "y",
  xFormat = fmtValue,
  yFormat = fmtValue,
  higherIsBetter = true,
}: ScatterParetoProps): ReactElement {
  const pts = points.filter((q) => isNum(q.x) && isNum(q.y));
  const H = height ?? Math.max(150, 26 * pts.length + 28);
  if (pts.length === 0) {
    return (
      <svg className="chart" width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label="No data">
        <text className="none" x={width / 2} y={H / 2} textAnchor="middle">
          no data
        </text>
      </svg>
    );
  }
  const [, x1] = niceExtent(0, Math.max(0, ...pts.map((q) => q.x)), 4);
  const lo = (q: ScatterPoint): number => (isNum(q.yLo) ? q.yLo : q.y);
  const hi = (q: ScatterPoint): number => (isNum(q.yHi) ? q.yHi : q.y);
  let y0 = Math.min(...pts.map(lo));
  let y1 = Math.max(...pts.map(hi));
  const pad = (y1 - y0) * 0.04 || Math.abs(y1) * 0.01 || 0.01;
  y0 -= pad;
  y1 += pad;
  const X = (v: number): number => M.l + (v / x1) * Math.max(1, width - M.l - M.r);
  const Y = (v: number): number => M.t + (1 - (v - y0) / (y1 - y0)) * Math.max(1, H - M.t - M.b);
  const yTicks = niceTicks(y0, y1, 5);
  const yTick = tickFormatter(yTicks);
  const xTicks = niceTicks(0, x1, 4);
  const front = paretoFront(pts, higherIsBetter)
    .map((q, i) => (i === 0 ? `M${X(q.x)},${Y(q.y)}` : `H${X(q.x)}V${Y(q.y)}`))
    .join("");
  return (
    <svg className="chart" width={width} height={H} viewBox={`0 0 ${width} ${H}`}>
      {yTicks.map((v) => (
        <g key={`y${v}`}>
          <line className="gl" x1={M.l} x2={width - M.r} y1={Y(v)} y2={Y(v)} />
          <text className="yt" x={M.l - 6} y={Y(v) + 3.5} textAnchor="end">
            {yTick(v)}
          </text>
        </g>
      ))}
      {xTicks.map((v) => (
        <g key={`x${v}`}>
          <line className="gl" x1={X(v)} x2={X(v)} y1={M.t} y2={H - M.b} />
          <text className="xt" x={X(v)} y={H - 6} textAnchor={v === 0 ? "start" : "middle"}>
            {xFormat(v)}
          </text>
        </g>
      ))}
      <line className="ax" x1={M.l} x2={width - M.r} y1={H - M.b} y2={H - M.b} />
      {front ? <path className="front" d={front} /> : null}
      {pts.map((q) => {
        const onMove = (e: MouseEvent<SVGGElement>): void =>
          showTip(e.clientX, e.clientY, q.name, [
            { color: q.color, value: yFormat(q.y), name: yName },
            { value: xFormat(q.x), name: xName },
          ]);
        return (
          <g key={q.id} className="pt" data-series={q.id} onMouseMove={onMove} onMouseLeave={hideTip}>
            <line className="err" x1={X(q.x)} x2={X(q.x)} y1={Y(lo(q))} y2={Y(hi(q))} stroke={q.color} />
            <circle className="hit" cx={X(q.x)} cy={Y(q.y)} r={12} />
            <circle className="dot" cx={X(q.x)} cy={Y(q.y)} r={4.5} fill={q.color} />
          </g>
        );
      })}
    </svg>
  );
}
