/**
 * The glyph language shared by every chart.
 *
 * - seed dots: one dot per seed, stacked when they would overlap;
 * - diamond with `×n`: n seeds that all gave one score (never a fake `± 0`);
 * - mean square plus whisker: the test-set 95% interval;
 * - best band: the best group's interval, drawn behind all rows;
 * - spike, kill, and checkpoint marks for training curves.
 */
import type { ReactElement } from "react";
import type { Pos } from "./Scale";
import "./charts.css";

/** Minimum horizontal gap in px before seed dots stack. */
export const SEED_GAP = 8;

/** A seed dot position after stacking. */
export interface StackedDot {
  x: number;
  level: number;
}

/**
 * Stack dots that would overlap into a tiny beeswarm.
 *
 * Positions are sorted; a dot closer than `gap` to the previous one sits one level
 * higher, otherwise it goes back to level 0.
 *
 * Parameters
 * ----------
 * xs : number[]
 *     Pixel positions.
 * gap : number
 *     Minimum distance before stacking.
 *
 * Returns
 * -------
 * StackedDot[]
 *     Sorted positions with their stack level.
 */
export function stackSeeds(xs: number[], gap = SEED_GAP): StackedDot[] {
  const out: StackedDot[] = [];
  let prev = Number.NEGATIVE_INFINITY;
  let level = 0;
  for (const x of [...xs].sort((a, b) => a - b)) {
    level = x - prev < gap ? level + 1 : 0;
    out.push({ x, level });
    prev = x;
  }
  return out;
}

/** One dot per seed value, stacked upward from `y`. */
export function SeedDots({
  x,
  values,
  y,
  r = 3.8,
}: {
  x: Pos;
  values: number[];
  y: number;
  r?: number;
}): ReactElement {
  return (
    <g className="seeds">
      {stackSeeds(values.filter(Number.isFinite).map(x)).map((d, i) => (
        <circle key={i} className="seed" cx={d.x} cy={y - d.level * SEED_GAP} r={r} />
      ))}
    </g>
  );
}

/** SVG path of a diamond centred on (`cx`, `cy`) with half-diagonal `r`. */
export function diamondPath(cx: number, cy: number, r: number): string {
  return `M${cx} ${cy - r}L${cx + r} ${cy}L${cx} ${cy + r}L${cx - r} ${cy}Z`;
}

/** A hollow diamond; green-washed when `best`. */
export function Diamond({
  cx,
  cy,
  r = 6.5,
  best = false,
}: {
  cx: number;
  cy: number;
  r?: number;
  best?: boolean;
}): ReactElement {
  return <path className={best ? "dia best" : "dia"} d={diamondPath(cx, cy, r)} />;
}

/** `n` identical seeds: a diamond plus a bold `×n` (left of the mark for the best row). */
export function IdenticalSeeds({
  cx,
  cy,
  n,
  best = false,
  r = 6.5,
}: {
  cx: number;
  cy: number;
  n: number;
  best?: boolean;
  r?: number;
}): ReactElement {
  const dx = r + 4.5;
  return (
    <g className="identical">
      <Diamond cx={cx} cy={cy} r={r} best={best} />
      <text
        className="lbl-b"
        x={best ? cx - dx : cx + dx}
        y={cy + 4}
        textAnchor={best ? "end" : "start"}
      >
        {`×${n}`}
      </text>
    </g>
  );
}

/** The group mean: a small rounded square. */
export function MeanMark({
  cx,
  cy,
  r = 4.5,
  best = false,
}: {
  cx: number;
  cy: number;
  r?: number;
  best?: boolean;
}): ReactElement {
  return (
    <rect
      className={best ? "mean best" : "mean"}
      x={cx - r}
      y={cy - r}
      width={2 * r}
      height={2 * r}
      rx={1.5}
    />
  );
}

/** A 95% interval: horizontal line with 8 px end caps. */
export function Whisker({
  x1,
  x2,
  y,
  best = false,
}: {
  x1: number;
  x2: number;
  y: number;
  best?: boolean;
}): ReactElement {
  return (
    <path
      className={best ? "whisk best" : "whisk"}
      d={`M${x1} ${y}H${x2}M${x1} ${y - 4}V${y + 4}M${x2} ${y - 4}V${y + 4}`}
    />
  );
}

/** The best group's interval as a washed band with edge lines. */
export function BestBand({
  x1,
  x2,
  y0,
  y1,
}: {
  x1: number;
  x2: number;
  y0: number;
  y1: number;
}): ReactElement {
  const a = Math.min(x1, x2);
  const b = Math.max(x1, x2);
  return (
    <g className="best-band">
      <rect className="band" x={a} y={y0} width={b - a} height={Math.max(0, y1 - y0)} />
      <line className="band-edge" x1={a} x2={a} y1={y0} y2={y1} />
      <line className="band-edge" x1={b} x2={b} y1={y0} y2={y1} />
    </g>
  );
}

/** A loss-spike glyph (a red peak), centred on (`x`, `y`), scaled by `s`. */
export function SpikeMark({ x, y, s = 1 }: { x: number; y: number; s?: number }): ReactElement {
  return (
    <path
      className="evg"
      d={`M${x - 6 * s} ${y + 4 * s}H${x - 2.5 * s}L${x} ${y - 5 * s}L${x + 2.5 * s} ${y + 4 * s}H${x + 6 * s}`}
    />
  );
}

/** A killed or failed run: a red cross. */
export function KillMark({ x, y, r = 3.5 }: { x: number; y: number; r?: number }): ReactElement {
  return (
    <path
      className="m-fail"
      d={`M${x - r} ${y - r}L${x + r} ${y + r}M${x + r} ${y - r}L${x - r} ${y + r}`}
    />
  );
}

/** A checkpoint: hollow ring, or a filled green dot for the best checkpoint. */
export function CheckpointMark({
  cx,
  cy,
  best = false,
}: {
  cx: number;
  cy: number;
  best?: boolean;
}): ReactElement {
  return best ? (
    <circle className="m-best ringed" cx={cx} cy={cy} r={4.5} />
  ) : (
    <circle className="ck" cx={cx} cy={cy} r={3.2} />
  );
}

/** Glyphs available in chart keys. */
export type KeyGlyphKind =
  | "seed"
  | "identical"
  | "whisker"
  | "band"
  | "seedLine"
  | "meanLine"
  | "bestCkpt"
  | "ckpt"
  | "spike"
  | "killed";

/** A small inline SVG of one glyph, for keys and table cells. */
export function KeyGlyph({ kind }: { kind: KeyGlyphKind }): ReactElement {
  const box = (w: number, body: ReactElement): ReactElement => (
    <svg className="hx-chart glyph" width={w} height={12} aria-hidden="true" data-glyph={kind}>
      {body}
    </svg>
  );
  switch (kind) {
    case "seed":
      return box(
        18,
        <>
          <circle className="seed" cx={5} cy={6} r={3.6} />
          <circle className="seed" cx={13} cy={6} r={3.6} />
        </>,
      );
    case "identical":
      return box(12, <Diamond cx={6} cy={6} r={5} />);
    case "whisker":
      return box(22, <path className="whisk" d="M2 6H20M2 2V10M20 2V10" />);
    case "band":
      return box(18, <BestBand x1={3} x2={15} y0={0} y1={12} />);
    case "seedLine":
      return box(22, <path className="sl" style={{ opacity: 1 }} d="M1 8L8 5L14 7L21 3" />);
    case "meanLine":
      return box(22, <path className="ml" d="M1 8L8 5L14 7L21 3" />);
    case "bestCkpt":
      return box(12, <circle className="m-best ringed" cx={6} cy={6} r={4} />);
    case "ckpt":
      return box(12, <circle className="ck" cx={6} cy={6} r={3.2} />);
    case "spike":
      return box(16, <SpikeMark x={8} y={6} s={0.9} />);
    case "killed":
      return box(12, <KillMark x={6} y={6} r={4} />);
  }
}

/** One entry of a chart key. */
export interface KeyItem {
  glyph: KeyGlyphKind;
  label: string;
  title?: string;
}

/** A chart key: glyph plus short label per item; explanations in `title`. */
export function Key({ items }: { items: KeyItem[] }): ReactElement {
  return (
    <div className="key" aria-label="Key">
      {items.map((it) => (
        <span key={`${it.glyph}-${it.label}`} title={it.title}>
          <KeyGlyph kind={it.glyph} />
          {it.label}
        </span>
      ))}
    </div>
  );
}
