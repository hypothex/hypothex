/**
 * Axis and grid primitives for SVG charts (journal style: hairline grid, small ticks).
 */
import type { ReactElement } from "react";
import type { Pos } from "./Scale";

/** Props for {@link AxisBottom}. */
export interface AxisBottomProps {
  /** Value to x pixel. */
  x: Pos;
  /** Tick values. */
  ticks: number[];
  /** Baseline y. */
  y: number;
  /** Left end of the axis line. */
  x0: number;
  /** Right end of the axis line. */
  x1: number;
  /** Tick label format. */
  format: (v: number) => string;
  /** Axis caption, drawn right-aligned under the tick labels. */
  label?: string;
  /** Label every n-th tick (1 = all). */
  every?: number;
}

/** Horizontal axis: baseline, 4 px ticks, labels, optional right-aligned caption. */
export function AxisBottom({
  x,
  ticks,
  y,
  x0,
  x1,
  format,
  label,
  every = 1,
}: AxisBottomProps): ReactElement {
  return (
    <g className="axis-b">
      <line className="axis" x1={x0} x2={x1} y1={y} y2={y} />
      {ticks.map((t, i) => (
        <g key={t}>
          <line className="axis" x1={x(t)} x2={x(t)} y1={y} y2={y + 4} />
          {i % every === 0 ? (
            <text className="tk" x={x(t)} y={y + 17} textAnchor="middle">
              {format(t)}
            </text>
          ) : null}
        </g>
      ))}
      {label ? (
        <text className="lbl-s" x={x1} y={y + 36} textAnchor="end">
          {label}
        </text>
      ) : null}
    </g>
  );
}

/** Vertical grid lines at `ticks`, from `y0` to `y1`. */
export function GridX({
  x,
  ticks,
  y0,
  y1,
}: {
  x: Pos;
  ticks: number[];
  y0: number;
  y1: number;
}): ReactElement {
  return (
    <g className="grid-x">
      {ticks.map((t) => (
        <line key={t} className="grid" x1={x(t)} x2={x(t)} y1={y0} y2={y1} />
      ))}
    </g>
  );
}

/** Horizontal grid lines at `ticks`, from `x0` to `x1`. */
export function GridY({
  y,
  ticks,
  x0,
  x1,
}: {
  y: Pos;
  ticks: number[];
  x0: number;
  x1: number;
}): ReactElement {
  return (
    <g className="grid-y">
      {ticks.map((t) => (
        <line key={t} className="grid" x1={x0} x2={x1} y1={y(t)} y2={y(t)} />
      ))}
    </g>
  );
}

/** Right-aligned y tick labels ending at `x`. */
export function AxisLeftLabels({
  y,
  ticks,
  x,
  format,
}: {
  y: Pos;
  ticks: number[];
  x: number;
  format: (v: number) => string;
}): ReactElement {
  return (
    <g className="axis-l">
      {ticks.map((t) => (
        <text key={t} className="tk" x={x} y={y(t) + 4} textAnchor="end">
          {format(t)}
        </text>
      ))}
    </g>
  );
}
