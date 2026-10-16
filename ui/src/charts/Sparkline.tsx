/** Best-over-time sparkline for the Home tasks table (spec 4.1), from the mockup's `spark`. */
import { type ReactElement } from "react";
import "./charts.css";

export interface SparklineProps {
  values: readonly number[];
  width?: number;
  height?: number;
  /** Lower is better: the lowest value is drawn at the top. */
  lowerIsBetter?: boolean;
  /** Accessible name, e.g. "best top1 over 7 days". */
  label?: string;
}

/** `x,y` pairs for a polyline; best at the top, 2 px inset, equal values in the middle. */
export function sparkPoints(values: readonly number[], width: number, height: number, lowerIsBetter: boolean): string {
  const vs = values.filter(Number.isFinite);
  if (vs.length === 0) return "";
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  const y = (v: number): number => {
    if (hi === lo) return height / 2;
    const t = lowerIsBetter ? (hi - v) / (hi - lo) : (v - lo) / (hi - lo);
    return height - 3 - t * (height - 6);
  };
  const r1 = (v: number): number => Math.round(v * 10) / 10;
  if (vs.length === 1) return `2,${r1(y(vs[0] ?? 0))} ${width - 2},${r1(y(vs[0] ?? 0))}`;
  return vs.map((v, i) => `${r1((i / (vs.length - 1)) * (width - 4) + 2)},${r1(y(v))}`).join(" ");
}

/** The sparkline svg, or nothing when there is no finite value. */
export function Sparkline({ values, width = 90, height = 22, lowerIsBetter = false, label }: SparklineProps): ReactElement | null {
  const points = sparkPoints(values, width, height, lowerIsBetter);
  if (!points) return null;
  return (
    <svg
      className="spark"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <polyline points={points} />
    </svg>
  );
}
