/**
 * Score panel (spec 4.2 "Scores", principle 6), ported from the mockup's `scoreChart`: every
 * visible config on one axis as a mean dot with its 95% test-set interval and seed dots, the
 * best config's interval as a green band behind all rows.
 */
import { type FocusEvent, type KeyboardEvent, type MouseEvent, type ReactElement } from "react";

import { cx } from "../lib/cx";
import { niceTicks, tickFormatter } from "../lib/ticks";
import { charsFor, clip } from "./labels";
import { useChartLabel } from "./chartLabel";
import { fmtValue } from "./Scale";
import { type TipRow, hideTip, showTip } from "./Tooltip";
import "./charts.css";
import { PaperReferenceMark } from "./Glyphs";

export interface DotCIRow {
  id: string;
  name: string;
  color: string;
  mean: number | null;
  /** 95% test-set interval; omit both when there is none. */
  lo?: number | null;
  hi?: number | null;
  seeds?: readonly number[];
  /** Seeds behind the mean (defaults to the seed count). */
  n?: number;
  best?: boolean;
  /** Why there is no interval, for the tooltip. */
  note?: string;
}

export interface DotCIReference { name: string; value: number; std?: number; source?: string }

export interface DotCIChartProps {
  references?: readonly DotCIReference[];
  rows: readonly DotCIRow[];
  width: number;
  band?: { lo: number; hi: number } | null;
  format?: (v: number) => string;
  highlight?: string | null;
  onOpen?: (id: string) => void;
}

export const DOT_MARGIN = { l: 132, r: 56, t: 6, b: 22 } as const;
export const DOT_ROW_H = 26;
export const NO_INTERVAL = "no interval: single seed, no per-example scores";

const isNum = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

function signed(d: number, format: (v: number) => string): string {
  return `${d > 0 ? "+" : d < 0 ? "−" : "±"}${format(Math.abs(d))}`;
}

/** The tooltip rows of one config. */
export function dotTipRows(row: DotCIRow, bestMean: number | null, format: (v: number) => string): TipRow[] {
  const n = row.n ?? row.seeds?.length ?? 1;
  const out: TipRow[] = [
    { color: row.color, value: isNum(row.mean) ? format(row.mean) : "—", name: `mean of ${n} seed${n === 1 ? "" : "s"}` },
    isNum(row.lo) && isNum(row.hi)
      ? { value: `${format(row.lo)}–${format(row.hi)}`, name: "95% CI (test set)" }
      : { value: "—", name: row.note ?? NO_INTERVAL },
  ];
  if (isNum(row.mean) && bestMean !== null) {
    out.push({ value: row.best ? "best" : signed(row.mean - bestMean, format), name: "Δ vs best" });
  }
  return out;
}

export function DotCIChart({ rows, references = [], width, band = null, format = fmtValue, highlight = null, onOpen }: DotCIChartProps): ReactElement {
  const label = useChartLabel("Scores by config");
  const m = DOT_MARGIN;
  const refs = references.filter((r) => isNum(r.value));
  const H = m.t + m.b + Math.max(1, rows.length + refs.length) * DOT_ROW_H;
  const vals: number[] = refs.map((r) => r.value);
  for (const r of rows) for (const v of [r.mean, r.lo, r.hi, ...(r.seeds ?? [])]) if (isNum(v)) vals.push(v);
  if (band) vals.push(band.lo, band.hi);
  // a named group, not role="img": its rows are focusable buttons
  const svgProps = { className: "chart", width, height: H, viewBox: `0 0 ${width} ${H}` } as const;
  if (vals.length === 0) {
    return (
      <svg {...svgProps} role="img" aria-label="No scores">
        <text className="none" x={width / 2} y={H / 2 + 4} textAnchor="middle">
          no scores
        </text>
      </svg>
    );
  }
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = (hi - lo) * 0.04 || Math.abs(hi) * 0.01 || 0.01;
  lo -= pad;
  hi += pad;
  const plotW = Math.max(1, width - m.l - m.r);
  const X = (v: number): number => m.l + ((v - lo) / (hi - lo)) * plotW;
  const ticks = niceTicks(lo, hi, Math.max(2, Math.min(8, Math.floor(plotW / 70))));
  const tick = tickFormatter(ticks);
  const nameChars = charsFor(m.l - 20);
  const bestMean = rows.find((r) => r.best && isNum(r.mean))?.mean ?? null;

  const tip = (r: DotCIRow) => (e: MouseEvent<SVGGElement>) => showTip(e.clientX, e.clientY, r.name, dotTipRows(r, bestMean, format));
  const focusTip = (r: DotCIRow) => (e: FocusEvent<SVGGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    showTip(box.left + m.l, box.top, r.name, dotTipRows(r, bestMean, format));
  };
  const key = (r: DotCIRow) => (e: KeyboardEvent<SVGGElement>) => {
    if (onOpen && e.key === "Enter") onOpen(r.id);
  };

  return (
    <svg {...svgProps} role="group" aria-label={label}>
      {ticks.map((v) => (
        <g key={v}>
          <line className="gl" x1={X(v)} x2={X(v)} y1={m.t} y2={H - m.b} />
          <text className="xt" x={X(v)} y={H - 6} textAnchor="middle">
            {tick(v)}
          </text>
        </g>
      ))}
      {band ? <rect className="band" x={X(band.lo)} y={m.t} width={Math.max(0, X(band.hi) - X(band.lo))} height={rows.length * DOT_ROW_H} /> : null}
      {rows.map((r, i) => {
        const cy = m.t + i * DOT_ROW_H + DOT_ROW_H / 2;
        const interval = isNum(r.lo) && isNum(r.hi);
        return (
          <g
            key={r.id}
            data-series={r.id}
            className={cx("row", onOpen && "link", highlight !== null && highlight !== r.id && "dim")}
            tabIndex={0}
            role={onOpen ? "button" : undefined}
            aria-label={`${r.name}: ${isNum(r.mean) ? format(r.mean) : "no score"}`}
            onMouseMove={tip(r)}
            onMouseLeave={hideTip}
            onFocus={focusTip(r)}
            onBlur={hideTip}
            onClick={onOpen ? () => onOpen(r.id) : undefined}
            onKeyDown={key(r)}
          >
            <rect className="hit" x={0} y={cy - DOT_ROW_H / 2} width={width} height={DOT_ROW_H} />
            <rect x={0} y={cy - 5} width={10} height={10} rx={2.5} fill={r.color} />
            <text className={cx("name", r.best && "best")} x={16} y={cy + 4}>
              {clip(r.name, nameChars)}
            </text>
            {interval ? (
              <>
                <line className="whisk" x1={X(r.lo as number)} x2={X(r.hi as number)} y1={cy} y2={cy} />
                <line className="whisk" x1={X(r.lo as number)} x2={X(r.lo as number)} y1={cy - 4} y2={cy + 4} />
                <line className="whisk" x1={X(r.hi as number)} x2={X(r.hi as number)} y1={cy - 4} y2={cy + 4} />
              </>
            ) : null}
            {(r.seeds ?? []).filter(isNum).map((v, k) => (
              <circle key={`s${k}`} className="sdot" cx={X(v)} cy={cy - 7} r={2.2} fill={r.color} />
            ))}
            {isNum(r.mean) ? <circle className="mdot" cx={X(r.mean)} cy={cy} r={4.5} fill={r.color} /> : null}
            <text className={cx(isNum(r.mean) ? "val" : "none", r.best && "best")} x={width - 4} y={cy + 4} textAnchor="end">
              {isNum(r.mean) ? format(r.mean) : "—"}
            </text>
          </g>
        );
      })}
      {refs.length ? <line x1={0} x2={width} y1={m.t + rows.length * DOT_ROW_H} y2={m.t + rows.length * DOT_ROW_H} stroke="var(--ink-3)" strokeDasharray="4 4" /> : null}
      {refs.map((reference, i) => {
        const cy = m.t + (rows.length + i) * DOT_ROW_H + DOT_ROW_H / 2;
        const description = `Published value ${format(reference.value)}${isNum(reference.std) ? `; published std ${format(reference.std)}` : ""}${reference.source ? `; ${reference.source}` : ""}`;
        return <g key={`${reference.name}:${i}`} data-reference={reference.name} tabIndex={0} aria-label={`${reference.name}: ${description}`}>
          <title>{description}</title>
          <text className="name" x={16} y={cy + 4}>{clip(reference.name, nameChars)}</text>
          <PaperReferenceMark x={X(reference.value)} y={cy} />
          <text className="val" x={width - 4} y={cy + 4} textAnchor="end">{format(reference.value)}</text>
        </g>;
      })}
    </svg>
  );
}
