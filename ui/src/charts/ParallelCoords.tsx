/**
 * Sweep parallel coordinates (spec 4.2 "Sweeps"), ported from the mockup's `parcoords`:
 * one line per finished run across its params and the score, coloured on a sequential ramp
 * by the score, axis labels above the lines with a halo, one tooltip per line.
 */
import { type ReactElement, useState } from "react";

import { cx } from "../lib/cx";
import { niceTicks, tickFormatter } from "../lib/ticks";
import { useChartLabel } from "./chartLabel";
import { fmtValue } from "./Scale";
import { type TipRow, hideTip, showTip } from "./Tooltip";
import "./charts.css";

export interface PCAxis {
  key: string;
  label: string;
  /** Categorical axis values, bottom to top; omit for a numeric axis. */
  values?: readonly string[];
}

export interface PCLine {
  id: string;
  name: string;
  values: Readonly<Record<string, string | number | null | undefined>>;
}

export interface ParallelCoordsProps {
  axes: readonly PCAxis[];
  lines: readonly PCLine[];
  width: number;
  height?: number;
  /** A numeric axis key; its value picks the line colour. */
  colorBy: string;
  /** Direction of `colorBy`: better values are darker and drawn last. */
  higherIsBetter?: boolean;
  format?: (v: number) => string;
  onOpen?: (id: string) => void;
}

/** Sequential blues from the mockup, low to high. */
export const SEQ_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"] as const;

/** The ramp colour for `t` in 0..1 (clamped). */
export function seqColor(t: number): string {
  const k = Math.min(SEQ_RAMP.length - 1, Math.max(0, Math.floor((Number.isFinite(t) ? t : 0) * SEQ_RAMP.length)));
  return SEQ_RAMP[k] ?? SEQ_RAMP[0];
}

const M = { l: 44, r: 56, t: 24, b: 14 } as const;

type Cell = string | number | null | undefined;

/** A numeric cell (a number or a non-blank numeric string), else null. */
function numOf(v: Cell): number | null {
  if (v === null || v === undefined || (typeof v === "string" && v.trim() === "")) return null;
  const x = Number(v);
  return Number.isFinite(x) ? x : null;
}

/** Whether `l` has a value on `a`: one of its categories, or a finite number. */
function hasValue(l: PCLine, a: PCAxis): boolean {
  const v = l.values[a.key];
  if (a.values) return v !== null && v !== undefined && a.values.includes(String(v));
  return numOf(v) !== null;
}

interface NumAxis {
  lo: number;
  hi: number;
  ticks: number[];
}

/** Parallel coordinates for a sweep: one bezier per complete line, best drawn last. */
export function ParallelCoords({
  axes,
  lines,
  width,
  height = 240,
  colorBy,
  higherIsBetter = true,
  format = fmtValue,
  onOpen,
}: ParallelCoordsProps): ReactElement {
  const [hot, setHot] = useState<string | null>(null);
  const label = useChartLabel("Parallel coordinates");
  const n = axes.length;
  const ph = height - M.t - M.b;
  const AX = (i: number): number => M.l + (n <= 1 ? (width - M.l - M.r) / 2 : (i * (width - M.l - M.r)) / (n - 1));
  // only lines with a value on every axis are drawn; their values set the numeric ranges
  const complete = lines.filter((l) => axes.every((a) => hasValue(l, a)));
  if (complete.length === 0) {
    return (
      <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="No runs">
        <text className="none" x={width / 2} y={height / 2} textAnchor="middle">
          no runs
        </text>
      </svg>
    );
  }
  const num = new Map<string, NumAxis>();
  for (const a of axes) {
    if (a.values) continue;
    const vs = complete.map((l) => numOf(l.values[a.key]) ?? 0);
    let lo = Math.min(...vs);
    let hi = Math.max(...vs);
    if (hi === lo) {
      const pad = Math.abs(hi) * 0.01 || 0.01;
      lo -= pad;
      hi += pad;
    }
    num.set(a.key, { lo, hi, ticks: niceTicks(lo, hi, 4) });
  }
  const yCat = (a: PCAxis, i: number): number => {
    const k = (a.values?.length ?? 1) - 1;
    return M.t + (k === 0 ? 0.5 : 1 - i / k) * ph;
  };
  const yNum = (axis: NumAxis, v: number): number => M.t + (1 - (v - axis.lo) / (axis.hi - axis.lo)) * ph;
  // spread lines that share a categorical value, in line order, 3 px apart
  const offset = new Map<string, number>();
  for (const a of axes) {
    if (!a.values) continue;
    const groups = new Map<string, string[]>();
    for (const l of complete) {
      const v = String(l.values[a.key]);
      groups.set(v, [...(groups.get(v) ?? []), l.id]);
    }
    for (const ids of groups.values()) {
      ids.forEach((id, k) => offset.set(`${a.key}\u0000${id}`, Math.max(-9, Math.min(9, (k - (ids.length - 1) / 2) * 3))));
    }
  }
  const color = num.get(colorBy);
  const colorOf = (l: PCLine): string => {
    const v = numOf(l.values[colorBy]);
    if (!color || v === null) return "var(--c0)";
    const t = (v - color.lo) / (color.hi - color.lo);
    return seqColor(higherIsBetter ? t : 1 - t);
  };
  const yOf = (l: PCLine, a: PCAxis): number => {
    if (a.values) return yCat(a, a.values.indexOf(String(l.values[a.key]))) + (offset.get(`${a.key}\u0000${l.id}`) ?? 0);
    const axis = num.get(a.key);
    return axis ? yNum(axis, numOf(l.values[a.key]) ?? axis.lo) : M.t;
  };
  // worst first, best last (on top)
  const dir = higherIsBetter ? 1 : -1;
  const rank = (l: PCLine): number => (color ? (numOf(l.values[colorBy]) ?? 0) : 0);
  const ordered = [...complete].sort((a, b) => dir * (rank(a) - rank(b)));
  const tipRows = (l: PCLine): TipRow[] =>
    axes.map((a, i) => {
      const v = l.values[a.key];
      return {
        color: i === 0 ? colorOf(l) : undefined,
        value: typeof v === "number" ? format(v) : String(v ?? "—"),
        name: a.label,
      };
    });
  const r1 = (v: number): number => Math.round(v * 10) / 10;
  return (
    <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      {axes.map((a, i) => (
        <line key={`ax-${a.key}`} className="ax" x1={AX(i)} x2={AX(i)} y1={M.t} y2={height - M.b} />
      ))}
      {ordered.map((l) => {
        const ys = axes.map((a) => yOf(l, a));
        let d = `M${r1(AX(0))},${r1(ys[0] ?? 0)}`;
        for (let i = 1; i < n; i++) {
          const mid = (AX(i - 1) + AX(i)) / 2;
          d += ` C${r1(mid)},${r1(ys[i - 1] ?? 0)} ${r1(mid)},${r1(ys[i] ?? 0)} ${r1(AX(i))},${r1(ys[i] ?? 0)}`;
        }
        return (
          <path
            key={l.id}
            className={cx("pc", hot === l.id && "on")}
            d={d}
            stroke={colorOf(l)}
            onMouseMove={(e) => {
              setHot(l.id);
              showTip(e.clientX, e.clientY, l.name, tipRows(l));
            }}
            onMouseLeave={() => {
              setHot(null);
              hideTip();
            }}
            onClick={onOpen ? () => onOpen(l.id) : undefined}
          />
        );
      })}
      {axes.map((a, i) => {
        const last = i === n - 1 && n > 1;
        const x = AX(i) + (last ? 6 : -6);
        const anchor = last ? "start" : "end";
        const axis = num.get(a.key);
        const fmt = axis ? tickFormatter(axis.ticks) : String;
        return (
          <g key={`lab-${a.key}`}>
            <text className="axis-t" x={AX(i)} y={12} textAnchor="middle">
              {a.label}
            </text>
            {a.values
              ? a.values.map((v, k) => (
                  <text key={v} className="halo" x={x} y={yCat(a, k) + 3.5} textAnchor={anchor}>
                    {v}
                  </text>
                ))
              : axis?.ticks.map((v) => (
                  <text key={v} className="halo" x={x} y={yNum(axis, v) + 3.5} textAnchor={anchor}>
                    {fmt(v)}
                  </text>
                ))}
          </g>
        );
      })}
    </svg>
  );
}
