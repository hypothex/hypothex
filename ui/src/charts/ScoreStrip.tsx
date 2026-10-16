/**
 * "Where it ranks" (spec 4.3), ported from the mockup's `strip`: one axis with the other
 * configs as ticks, this run's sibling seeds as faint dots, this run as a large dot, and the
 * best config's 95% interval as a green band.
 */
import { type ReactElement } from "react";

import { niceTicks, tickFormatter } from "../lib/ticks";
import { fmtValue } from "./Scale";
import { hideTip, showTip } from "./Tooltip";
import "./charts.css";

export interface StripMark {
  kind: "this" | "seed" | "other";
  value: number;
  color?: string;
  /** Tooltip name, e.g. the config name. */
  label?: string;
}

export interface ScoreStripProps {
  width: number;
  marks: readonly StripMark[];
  band?: readonly [number, number] | null;
  lo?: number;
  hi?: number;
  format?: (v: number) => string;
}

const H = 46;
const M = { l: 6, r: 6, t: 8, b: 18 } as const;
const WORD = { this: "this run", seed: "other seed", other: "other config" } as const;

export function ScoreStrip({ width, marks, band = null, lo, hi, format = fmtValue }: ScoreStripProps): ReactElement {
  const vals = marks.map((mk) => mk.value).filter(Number.isFinite);
  if (band) vals.push(band[0], band[1]);
  const svgProps = { className: "chart", width, height: H, viewBox: `0 0 ${width} ${H}`, role: "img" } as const;
  if (vals.length === 0 && (lo === undefined || hi === undefined)) return <svg {...svgProps} aria-label="No scores" />;
  let d0 = lo ?? Math.min(...vals);
  let d1 = hi ?? Math.max(...vals);
  if (lo === undefined || hi === undefined || !(d1 > d0)) {
    const pad = (d1 - d0) * 0.04 || Math.abs(d1) * 0.01 || 0.01;
    d0 -= pad;
    d1 += pad;
  }
  const X = (v: number): number => M.l + ((v - d0) / (d1 - d0)) * (width - M.l - M.r);
  const cy = M.t + 10;
  const ticks = niceTicks(d0, d1, width > 600 ? 8 : 5);
  const tick = tickFormatter(ticks);
  const tipFor = (mk: StripMark) => (e: { clientX: number; clientY: number }) =>
    showTip(e.clientX, e.clientY, mk.label ?? WORD[mk.kind], [{ color: mk.color, value: format(mk.value), name: WORD[mk.kind] }]);
  const of = (kind: StripMark["kind"]) => marks.filter((mk) => mk.kind === kind && Number.isFinite(mk.value));
  return (
    <svg {...svgProps}>
      {band ? <rect className="sband" x={X(band[0])} y={M.t} width={Math.max(0, X(band[1]) - X(band[0]))} height={20} rx={4} /> : null}
      <line className="ax" x1={M.l} x2={width - M.r} y1={cy} y2={cy} />
      {ticks.map((v) => (
        <g key={v}>
          <line className="ax" x1={X(v)} x2={X(v)} y1={cy + 7} y2={cy + 10} />
          <text className="xt" x={X(v)} y={H - 3} textAnchor="middle">
            {tick(v)}
          </text>
        </g>
      ))}
      {of("other").map((mk, i) => (
        <line key={`o${i}`} className="other" x1={X(mk.value)} x2={X(mk.value)} y1={cy - 5} y2={cy + 5} onMouseMove={tipFor(mk)} onMouseLeave={hideTip} />
      ))}
      {of("seed").map((mk, i) => (
        <circle key={`s${i}`} className="sdot faint" cx={X(mk.value)} cy={cy} r={3.5} fill={mk.color ?? "var(--c0)"} onMouseMove={tipFor(mk)} onMouseLeave={hideTip} />
      ))}
      {of("this").map((mk, i) => (
        <circle key={`t${i}`} className="dot" cx={X(mk.value)} cy={cy} r={6} fill={mk.color ?? "var(--c1)"} onMouseMove={tipFor(mk)} onMouseLeave={hideTip} />
      ))}
    </svg>
  );
}
