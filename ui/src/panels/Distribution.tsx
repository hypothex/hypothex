/**
 * Distribution panel: ECDF per group plus p50/p95/p99 ticks and per-seed p95 dots.
 *
 * The x axis is log by default (latency); `meta.scale = "linear"` switches it.
 * `meta.render = "table"` draws the percentile table with the change vs the baseline instead.
 */
import { scaleLinear, scaleLog } from "d3-scale";
import { curveStepAfter, line } from "d3-shape";
import type { CSSProperties } from "react";
import type { DistributionRow } from "../api/models";
import { FS, useElementWidth } from "../charts/Scale";
import { axisTitle, fmtNum } from "../charts/valueFormat";
import type { PanelResult } from "./index";

/** One group's distribution row (contract 1.6). */
export type DistRow = DistributionRow;
/** One seed's percentiles. */
export type DistSeed = DistRow["seeds"][number];
type Quantile = "p50" | "p95" | "p99";
type Scale = "linear" | "log";

/**
 * Categorical series colours, fixed order, light and dark steps. The same values are the
 * `--cat-1` .. `--cat-5` tokens in `styles/palette.css`; these arrays are the fallback
 * when a token cannot be read (Vega needs concrete colours).
 *
 * Checked with the dataviz palette validator: light passes with adjacent CVD dE >= 15.7
 * (the yellow slot is below 3:1 contrast, so every series is also direct-labelled); dark
 * passes with adjacent CVD dE >= 16.7.
 */
export const SERIES_LIGHT = ["#2a78d6", "#e0602e", "#b8447e", "#eda100", "#4a3aa7"] as const;
export const SERIES_DARK = ["#4a90e8", "#e06a35", "#c95aa8", "#c98500", "#9085e9"] as const;

/** Colour for series `i`: the `--cat-N` token. Series past the fifth share muted ink. */
export function seriesColor(i: number): string {
  if (i < 0 || i >= SERIES_LIGHT.length) return "var(--ink-3)";
  return `var(--cat-${i + 1})`;
}

const MANTISSAS = [1, 2, 5] as const;
const r12 = (v: number): number => Number(v.toPrecision(12));

/** Widen `[lo, hi]` (both > 0) to the enclosing 1-2-5 values. */
export function niceLogDomain(lo: number, hi: number): [number, number] {
  const e0 = Math.floor(Math.log10(lo));
  let dLo = r12(10 ** e0);
  for (const m of MANTISSAS) if (r12(m * 10 ** e0) <= lo) dLo = r12(m * 10 ** e0);
  const e1 = Math.floor(Math.log10(hi));
  let dHi = r12(10 ** (e1 + 1));
  for (const m of [5, 2, 1]) if (r12(m * 10 ** e1) >= hi) dHi = r12(m * 10 ** e1);
  if (dHi <= dLo) dHi = r12(dLo * 10);
  return [dLo, dHi];
}

/** All 1-2-5 values inside `[lo, hi]`. */
export function logTicks(lo: number, hi: number): number[] {
  const out: number[] = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.floor(Math.log10(hi)); e++) {
    for (const m of MANTISSAS) {
      const v = r12(m * 10 ** e);
      if (v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9)) out.push(v);
    }
  }
  return out;
}

/** Signed percent number: `−30`, `+4.1` (U+2212 minus), `digits` decimals. */
export function signedPctNum(v: number, digits = 0): string {
  return `${v < 0 ? "−" : "+"}${Math.abs(v * 100).toFixed(digits)}`;
}

/** Signed percent: `−30%`, `+4%`. */
export function signedPct(v: number, digits = 0): string {
  return `${signedPctNum(v, digits)}%`;
}

/** Axis tick text: `0.05`, `20`, `1,000`. */
export function fmtTick(v: number): string {
  return Math.abs(v) >= 1000 ? v.toLocaleString("en-US") : String(Number(v.toPrecision(3)));
}

/** A linear or log (clamped) position function over `domain` mapped to `range`. */
export function xScale(
  kind: Scale,
  domain: [number, number],
  range: [number, number],
): (v: number) => number {
  const s =
    kind === "log"
      ? scaleLog().domain(domain).range(range).clamp(true)
      : scaleLinear().domain(domain).range(range);
  return (v: number) => s(v);
}

/** Domain and ticks for an x axis over `values`. Log drops values <= 0. */
export function xAxis(
  kind: Scale,
  values: number[],
): { domain: [number, number]; ticks: number[] } {
  const vs = values.filter((v) => Number.isFinite(v) && (kind === "linear" || v > 0));
  if (vs.length === 0) {
    return kind === "log"
      ? { domain: [1, 10], ticks: [1, 2, 5, 10] }
      : { domain: [0, 1], ticks: [0, 0.5, 1] };
  }
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  if (kind === "log") {
    const domain = niceLogDomain(lo, hi);
    const all = logTicks(domain[0], domain[1]);
    const pow10 = (t: number) => r12(10 ** Math.round(Math.log10(t))) === t;
    return { domain, ticks: all.length > 8 ? all.filter(pow10) : all };
  }
  const s = scaleLinear()
    .domain([Math.min(0, lo), hi === lo ? lo + 1 : hi])
    .nice(6);
  const [d0, d1] = s.domain();
  return { domain: [d0, d1], ticks: s.ticks(6) };
}

// geometry in CSS px; the width is measured
/** Width used before layout is known (and in test DOMs). */
export const DIST_FALLBACK_W = 720;
const PL = 132;
const PR = 16;
/** Top of the ECDF plot; the `share` axis title sits above it, clear of the `1` tick. */
export const TOP = 26;
const EH = 180;
const GAP = 34;
const RH = 36;
const TICK_HALF = { p50: 7, p95: 10, p99: 13 } as const;
const TICK_WIDTH = { p50: 1.25, p95: 2, p99: 1.25 } as const;
const QS = ["p50", "p95", "p99"] as const;

const T = {
  tk: { fontSize: FS.tick, fill: "var(--ink-3)", fontVariantNumeric: "tabular-nums" },
  lbl: { fontSize: FS.label, fill: "var(--ink-2)" },
  lblB: { fontSize: FS.label, fill: "var(--ink)", fontWeight: 600 },
  lblS: { fontSize: FS.tick, fill: "var(--ink-3)" },
  axis: { stroke: "var(--ink-3)", strokeWidth: 1 },
  grid: { stroke: "var(--rule-2)", strokeWidth: 1 },
  hair: { stroke: "var(--rule)", strokeWidth: 1 },
  seed: { fill: "var(--ink-3)", stroke: "var(--paper)", strokeWidth: 1.5 },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
  table: {
    borderCollapse: "collapse",
    width: "100%",
    fontSize: 13,
    fontVariantNumeric: "tabular-nums",
  },
  th: {
    fontSize: 11.5,
    fontWeight: 400,
    color: "var(--ink-3)",
    textAlign: "right",
    padding: "0 0 6px 12px",
    borderBottom: "1px solid var(--rule)",
  },
  td: {
    textAlign: "right",
    padding: "6px 0 6px 12px",
    borderBottom: "1px solid var(--rule-2)",
    color: "var(--ink)",
    verticalAlign: "top",
  },
  tdLabel: {
    textAlign: "left",
    padding: "6px 12px 6px 0",
    borderBottom: "1px solid var(--rule-2)",
    color: "var(--ink)",
    fontWeight: 600,
    verticalAlign: "top",
  },
  delta: { display: "block", fontSize: 11.5, color: "var(--ink-2)" },
  ref: { display: "block", fontSize: 11.5, color: "var(--ink-3)" },
} satisfies Record<string, CSSProperties>;

/** One percentile cell's tooltip: per-seed values, then the change vs the baseline. */
function cellTip(r: DistRow, q: Quantile, isBase: boolean): string {
  const repeats = r.seeds.map((s) => fmtNum(s[q])).join(", ");
  const head = `${r.label} ${q}: repeats ${repeats || "—"}`;
  if (isBase) return `${head}\nbaseline`;
  const d = r.vs_baseline?.[q];
  if (!d) return head;
  const [rel, lo, hi] = d;
  const ci =
    lo !== null && hi !== null
      ? `, 95% CI ${signedPctNum(lo, 1)} to ${signedPct(hi, 1)}`
      : ", one repeat: no CI";
  return `${head}\nvs baseline ${signedPct(rel, 1)}${ci}`;
}

/**
 * Percentile table: a row per group, p50/p95/p99 columns. Each cell shows the pooled value
 * and, below it, `ref` on the baseline row or the change vs the baseline with its 95% CI.
 */
function PercentileTable({
  rows,
  unit,
  baseline,
}: {
  rows: DistRow[];
  unit: string;
  baseline: string | null;
}) {
  const u = unit ? ` ${unit}` : "";
  return (
    <table data-testid="ptable" style={T.table}>
      <thead>
        <tr>
          <th style={{ ...T.th, textAlign: "left", padding: "0 12px 6px 0" }} />
          {QS.map((q) => (
            <th key={q} style={T.th}>{`${q}${u}`}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const isBase = r.group_id === baseline;
          return (
            <tr key={r.group_id} data-group={r.group_id}>
              <td style={T.tdLabel}>{r.label}</td>
              {QS.map((q) => {
                const d = isBase ? null : (r.vs_baseline?.[q] ?? null);
                return (
                  <td key={q} data-q={q} title={cellTip(r, q, isBase)} style={T.td}>
                    {fmtNum(r[q])}
                    {isBase && (
                      <small data-delta="ref" style={T.ref}>
                        ref
                      </small>
                    )}
                    {d && (
                      <small data-delta={q} style={T.delta}>
                        {signedPct(d[0])}
                        {d[1] !== null && d[2] !== null
                          ? ` [${signedPctNum(d[1])}, ${signedPctNum(d[2])}]`
                          : ""}
                      </small>
                    )}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * Distribution panel. Reads `meta.scale`, `meta.unit`, `meta.x_label`, `meta.name` (the
 * sample name), `meta.render` and `meta.baseline` (the backend sends
 * `{name, scale, render, baseline}`).
 */
export function DistributionPanel({ result }: { result: PanelResult }) {
  const [ref, W] = useElementWidth<HTMLDivElement>(DIST_FALLBACK_W);
  const rows = result.rows as unknown as DistRow[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  if (rows.length === 0) return <p style={T.empty}>No samples</p>;
  const unit = typeof meta.unit === "string" ? meta.unit : "";
  if (meta.render === "table") {
    const baseline = typeof meta.baseline === "string" ? meta.baseline : null;
    return <PercentileTable rows={rows} unit={unit} baseline={baseline} />;
  }
  // Explicit configured baseline semantics: orange reference, blue first alternative.
  // Generic distributions retain their ordinal palette, even if a label says "baseline".
  const baseline = typeof meta.baseline === "string" && rows.some((r) => r.group_id === meta.baseline) ? meta.baseline : null;
  const alternatives = rows.filter((r) => r.group_id !== baseline);
  const color = (row: DistRow, index: number): string => {
    if (!baseline) return seriesColor(index);
    if (row.group_id === baseline) return seriesColor(1);
    const slot = alternatives.findIndex((r) => r.group_id === row.group_id);
    return seriesColor(slot === 0 ? 0 : slot + 1);
  };
  const kind: Scale = meta.scale === "linear" ? "linear" : "log";
  const name = typeof meta.name === "string" ? meta.name : "";
  const xLabel =
    typeof meta.x_label === "string" ? meta.x_label : axisTitle(name, unit, { log: kind === "log" });

  const values = rows.flatMap((r) => [
    r.p50,
    r.p95,
    r.p99,
    ...r.ecdf.map((p) => p[0]),
    ...r.seeds.flatMap((s) => [s.p50, s.p95, s.p99]),
  ]);
  const { domain, ticks } = xAxis(kind, values);
  const X = xScale(kind, domain, [PL, W - PR]);
  const yE = TOP + EH;
  const Y = (p: number) => yE - p * EH;
  const rowsTop = yE + GAP;
  const yA = rowsTop + RH * rows.length + 4;
  const H = yA + 40;
  const path = line<[number, number]>()
    .x((d) => X(d[0]))
    .y((d) => Y(d[1]))
    .curve(curveStepAfter);
  const u = unit ? ` ${unit}` : "";

  return (
    <div ref={ref}>
    <svg
      width={W}
      height={H}
      role="img"
      aria-label={`Distributions of ${rows.length} groups, ${kind} scale, with p50, p95 and p99 ticks`}
      style={{ display: "block", overflow: "visible", fontFamily: "var(--sans)" }}
    >
      {ticks.map((t) => (
        <line key={`g${t}`} x1={X(t)} x2={X(t)} y1={TOP} y2={yA} style={T.grid} />
      ))}
      {[0, 0.5, 1].map((p) => (
        <g key={`y${p}`}>
          <line x1={PL} x2={W - PR} y1={Y(p)} y2={Y(p)} style={p === 0 ? T.axis : T.grid} />
          <text x={PL - 8} y={Y(p) + 4} textAnchor="end" style={T.tk}>
            {p}
          </text>
        </g>
      ))}
      <text data-testid="share" x={PL} y={TOP - 14} textAnchor="middle" style={T.lblS}>
        share
      </text>
      {rows.map((r, i) => {
        const pts = r.ecdf.filter((p) => kind === "linear" || p[0] > 0);
        if (pts.length === 0) return null;
        const d = path([[pts[0][0], 0], ...pts]) ?? "";
        return (
          <path
            key={`e${r.group_id}`}
            data-testid="ecdf"
            d={d}
            style={{
              fill: "none",
              stroke: color(r, i),
              strokeWidth: 2,
              strokeLinejoin: "round",
            }}
          >
            <title>{`${r.label}\nn = ${fmtNum(r.n)}`}</title>
          </path>
        );
      })}
      {QS.map((q) => (
        <text key={`h${q}`} x={X(rows[0][q])} y={rowsTop - 10} textAnchor="middle" style={T.lblS}>
          {q}
        </text>
      ))}
      {rows.map((r, i) => {
        const cy = rowsTop + RH * i + RH / 2;
        return (
          <g key={`r${r.group_id}`} data-group={r.group_id}>
            <line
              x1={0}
              x2={14}
              y1={cy}
              y2={cy}
              style={{ stroke: color(r, i), strokeWidth: 2.5 }}
            />
            <text x={20} y={cy + 4} style={T.lblB}>
              {r.label}
            </text>
            <line x1={PL} x2={W - PR} y1={cy} y2={cy} style={T.grid} />
            {r.seeds.map((s) => (
              <circle
                key={s.run_id}
                data-seed={s.run_id}
                cx={X(s.p95)}
                cy={cy}
                r={3.2}
                style={T.seed}
              >
                <title>{`${s.run_id}\np50 ${fmtNum(s.p50)}${u}, p95 ${fmtNum(s.p95)}${u}, p99 ${fmtNum(s.p99)}${u}`}</title>
              </circle>
            ))}
            {QS.map((q) => (
              <line
                key={q}
                data-q={q}
                x1={X(r[q])}
                x2={X(r[q])}
                y1={cy - TICK_HALF[q]}
                y2={cy + TICK_HALF[q]}
                style={{ stroke: "var(--ink)", strokeWidth: TICK_WIDTH[q] }}
              >
                <title>{`${r.label} ${q} ${fmtNum(r[q])}${u}\nn = ${fmtNum(r.n)}, ${r.seeds.length} seeds`}</title>
              </line>
            ))}
          </g>
        );
      })}
      <line x1={PL} x2={W - PR} y1={yA} y2={yA} style={T.axis} />
      {ticks.map((t) => (
        <g key={`t${t}`}>
          <line x1={X(t)} x2={X(t)} y1={yA} y2={yA + 4} style={T.axis} />
          <text data-tick={fmtTick(t)} x={X(t)} y={yA + 17} textAnchor="middle" style={T.tk}>
            {fmtTick(t)}
          </text>
        </g>
      ))}
      <text x={W - PR} y={yA + 34} textAnchor="end" style={T.lblS}>
        {xLabel}
      </text>
    </svg>
    </div>
  );
}

export default DistributionPanel;
