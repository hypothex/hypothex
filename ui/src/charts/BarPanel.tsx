/**
 * Score-key bar panels (spec 4.2 "Score keys") and the Compare panel's grouped bars, ported
 * from the mockup's `barPanel` and `groupedBars`: horizontal bars from zero in run colours,
 * the value at the bar end, the best value green, CI whiskers on the primary key.
 */
import { type MouseEvent, type ReactElement } from "react";

import { cx } from "../lib/cx";
import { niceExtent, niceTicks, tickFormatter } from "../lib/ticks";
import { useChartLabel } from "./chartLabel";
import { clip } from "./labels";
import { fmtValue } from "./Scale";
import { type TipRow, hideTip, showTip } from "./Tooltip";
import "./charts.css";

export interface BarRow {
  id: string;
  name: string;
  color: string;
  value: number | null;
  ci?: { lo: number; hi: number; method?: string } | null;
  best?: boolean;
}

export interface BarPanelProps {
  rows: readonly BarRow[];
  width: number;
  /** Score key or metric name, shown in the tooltip. */
  metric: string;
  format?: (v: number) => string;
  highlight?: string | null;
}

export const BAR_ROW_H = 24;
const isNum = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

/** A zero-based domain and its ticks over `vals`. */
function zeroDomain(vals: readonly number[]): { d0: number; d1: number; ticks: number[] } {
  if (vals.length === 0) return { d0: 0, d1: 1, ticks: niceTicks(0, 1, 4) };
  const [d0, d1] = niceExtent(Math.min(0, ...vals), Math.max(0, ...vals), 4);
  return { d0, d1, ticks: niceTicks(d0, d1, 4) };
}

/** The calm empty state: an svg of `height` with "no scores" in the middle. */
function NoScores({ width, height }: { width: number; height: number }): ReactElement {
  return (
    <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="No scores">
      <text className="none" x={width / 2} y={height / 2 + 4} textAnchor="middle">
        no scores
      </text>
    </svg>
  );
}

/** Vertical grid lines and x tick labels; the first label is left-aligned on the plot edge. */
interface XAxisProps {
  ticks: readonly number[];
  d0: number;
  X: (v: number) => number;
  /** Top and bottom of the plot area. */
  y0: number;
  y1: number;
}

function XAxis({ ticks, d0, X, y0, y1 }: XAxisProps): ReactElement {
  const tick = tickFormatter(ticks);
  return (
    <>
      {ticks.map((v) => (
        <g key={v}>
          <line className="gl" x1={X(v)} x2={X(v)} y1={y0} y2={y1} />
          <text className="xt" x={X(v)} y={y1 + 14} textAnchor={v === d0 ? "start" : "middle"}>
            {tick(v)}
          </text>
        </g>
      ))}
    </>
  );
}

export function BarPanel({ rows, width, metric, format = fmtValue, highlight = null }: BarPanelProps): ReactElement {
  const label = useChartLabel(`${metric} by run`);
  const lch = Math.min(Math.max(6, ...rows.map((r) => r.name.length)), 22);
  const m = { l: Math.min(150, Math.round(lch * 6.4) + 10), r: 46, t: 4, b: 20 };
  const H = m.t + m.b + Math.max(1, rows.length) * BAR_ROW_H;
  if (rows.length === 0) return <NoScores width={width} height={H} />;
  const vals = rows.flatMap((r) => [r.value, r.ci?.lo, r.ci?.hi]).filter(isNum);
  const { d0, d1, ticks } = zeroDomain(vals);
  const X = (v: number): number => m.l + ((v - d0) / (d1 - d0)) * Math.max(1, width - m.l - m.r);
  const tipRows = (r: BarRow): TipRow[] => [
    { color: r.color, value: isNum(r.value) ? format(r.value) : "not reported", name: metric },
    ...(r.ci ? [{ value: `${format(r.ci.lo)}–${format(r.ci.hi)}`, name: `95% CI${r.ci.method ? ` · ${r.ci.method}` : ""}` }] : []),
  ];
  return (
    <svg className="chart" width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label={label}>
      <XAxis ticks={ticks} d0={d0} X={X} y0={m.t} y1={H - m.b} />
      {rows.map((r, i) => {
        const cy = m.t + i * BAR_ROW_H + BAR_ROW_H / 2;
        const onMove = (e: MouseEvent<SVGGElement>): void => showTip(e.clientX, e.clientY, r.name, tipRows(r));
        return (
          <g
            key={r.id}
            data-series={r.id}
            className={cx("row", highlight !== null && highlight !== r.id && "dim")}
            onMouseMove={onMove}
            onMouseLeave={hideTip}
          >
            <rect className="hit" x={0} y={cy - BAR_ROW_H / 2} width={width} height={BAR_ROW_H} />
            <text className="lbl" x={0} y={cy + 4}>
              {clip(r.name, lch)}
            </text>
            {isNum(r.value) ? (
              <>
                <rect
                  className="bar"
                  x={X(Math.min(0, r.value))}
                  y={cy - 7}
                  width={Math.max(2, Math.abs(X(r.value) - X(0)))}
                  height={14}
                  rx={2}
                  fill={r.color}
                />
                {r.ci ? (
                  <>
                    <line className="ci" x1={X(r.ci.lo)} x2={X(r.ci.hi)} y1={cy} y2={cy} />
                    <line className="ci" x1={X(r.ci.lo)} x2={X(r.ci.lo)} y1={cy - 4} y2={cy + 4} />
                    <line className="ci" x1={X(r.ci.hi)} x2={X(r.ci.hi)} y1={cy - 4} y2={cy + 4} />
                  </>
                ) : null}
                <text className={cx("val", r.best && "best")} x={Math.max(X(r.value), X(0), r.ci ? X(r.ci.hi) : 0) + 5} y={cy + 4}>
                  {format(r.value)}
                </text>
              </>
            ) : (
              <text className="none" x={m.l + 2} y={cy + 4}>
                not reported
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export interface BarSeries {
  id: string;
  name: string;
  color: string;
}

export interface GroupedBarsProps {
  /** Datasets, top to bottom. */
  categories: readonly string[];
  /** Runs, one bar each inside every category. */
  series: readonly BarSeries[];
  valueOf: (category: string, seriesId: string) => number | null;
  width: number;
  /** The best value of a category (drawn green), or null. */
  best?: (category: string) => number | null;
  format?: (v: number) => string;
}

export function GroupedBars({ categories, series, valueOf, width, best, format = fmtValue }: GroupedBarsProps): ReactElement {
  const label = useChartLabel("Grouped bars");
  const barH = 12;
  const gap = 3;
  const catPad = 14;
  const m = { l: 118, r: 50, t: 4, b: 20 };
  const catH = Math.max(1, series.length) * (barH + gap) + catPad;
  const H = m.t + m.b + Math.max(1, categories.length) * catH;
  if (categories.length === 0 || series.length === 0) return <NoScores width={width} height={H} />;
  const vals = categories.flatMap((c) => series.map((s) => valueOf(c, s.id))).filter(isNum);
  const { d0, d1, ticks } = zeroDomain(vals);
  const X = (v: number): number => m.l + ((v - d0) / (d1 - d0)) * Math.max(1, width - m.l - m.r);
  return (
    <svg className="chart" width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label={label}>
      <XAxis ticks={ticks} d0={d0} X={X} y0={m.t} y1={H - m.b} />
      {categories.map((c, ci) => {
        const y0 = m.t + ci * catH;
        const bestV = best?.(c) ?? null;
        return (
          <g key={c}>
            {ci > 0 ? <line className="sep" x1={0} x2={width - m.r} y1={y0 - 2} y2={y0 - 2} /> : null}
            <text className="cat" x={0} y={y0 + catH / 2 - catPad / 2 + 4}>
              {clip(c, 16)}
            </text>
            {series.map((s, si) => {
              const v = valueOf(c, s.id);
              const y = y0 + si * (barH + gap) + catPad / 2;
              const onMove = (e: MouseEvent<SVGGElement>): void =>
                showTip(e.clientX, e.clientY, c, [{ color: s.color, value: isNum(v) ? format(v) : "—", name: s.name }]);
              return (
                <g key={s.id} data-series={s.id} className="row" onMouseMove={onMove} onMouseLeave={hideTip}>
                  <rect className="hit" x={m.l} y={y - 1} width={Math.max(0, width - m.l)} height={barH + 2} />
                  {isNum(v) ? (
                    <>
                      <rect
                        className="bar"
                        x={X(Math.min(0, v))}
                        y={y}
                        width={Math.max(2, Math.abs(X(v) - X(0)))}
                        height={barH}
                        rx={2}
                        fill={s.color}
                      />
                      <text className={cx("val", v === bestV && "best")} x={Math.max(X(v), X(0)) + 4} y={y + barH - 2}>
                        {format(v)}
                      </text>
                    </>
                  ) : null}
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}
