/**
 * Scatter panel: one point per group with 95% whiskers on both axes, faint seed dots, and
 * a dashed Pareto staircase through the groups the query engine marked `pareto: true`.
 * On an ordinal x (`meta.x_type = "ordinal"`, e.g. versions) rows sit in equal bands in
 * row order, and rows the engine marked `regression: true` are drawn in the failure colour.
 * The best group comes from the server (`meta.best_group`, in the y metric's own direction
 * `meta.y_higher_is_better`), never from the Pareto settings.
 */
import { scaleLinear } from "d3-scale";
import type { CSSProperties } from "react";
import type { ScatterMeta, ScatterRow } from "../api/models";
import { FS, useElementWidth } from "../charts/Scale";
import { axisTitle, fmtNum, valueFormatter, withUnit } from "../charts/valueFormat";
import { fmtTick, xAxis, xScale } from "./Distribution";
import type { PanelResult } from "./index";

/** Optimisation direction of one axis. */
export type Dir = "min" | "max";
/** One group's scatter row and the panel meta (contract 1.6). */
export type { ScatterMeta, ScatterRow };

/**
 * Vertices of the Pareto staircase in data space.
 *
 * Points are sorted by x. When lower x is better (`xDir = "min"`) each step goes across then
 * up/down; when higher x is better it goes up/down then across. `tailTo` extends the line to
 * the far edge of the x domain on the dominated side.
 */
export function paretoPath(
  front: { x: number; y: number }[],
  xDir: Dir,
  tailTo?: number,
): [number, number][] {
  if (front.length === 0) return [];
  const pts = [...front].sort((a, b) => a.x - b.x);
  const out: [number, number][] = [[pts[0].x, pts[0].y]];
  for (const p of pts.slice(1)) {
    const prev = out[out.length - 1];
    if (xDir === "min") out.push([p.x, prev[1]], [p.x, p.y]);
    else out.push([prev[0], p.y], [p.x, p.y]);
  }
  if (tailTo !== undefined) {
    if (xDir === "min") out.push([tailTo, out[out.length - 1][1]]);
    else out.unshift([tailTo, out[0][1]]);
  }
  return out;
}

/**
 * Index of the best row: the row of `bestGroup` when it is a string, -1 when it is null
 * (the server found no best group), else the best y for `yDir`; -1 if `rows` is empty.
 */
export function bestIndex(rows: ScatterRow[], yDir: Dir, bestGroup?: string | null): number {
  if (bestGroup === null) return -1;
  if (bestGroup !== undefined) return rows.findIndex((r) => r.group_id === bestGroup);
  let best = -1;
  rows.forEach((r, i) => {
    if (best < 0 || (yDir === "max" ? r.y > rows[best].y : r.y < rows[best].y)) best = i;
  });
  return best;
}

function dirOf(v: unknown, fallback: Dir): Dir {
  return v === "min" || v === "max" ? v : fallback;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * Direction of y for the best-group highlight: `meta.y_higher_is_better` (the metric's own
 * direction, set by the server whatever the Pareto settings), else `meta.pareto.y`, else
 * higher is better.
 */
export function yDirOf(meta: Record<string, unknown>): Dir {
  if (typeof meta.y_higher_is_better === "boolean") return meta.y_higher_is_better ? "max" : "min";
  return dirOf(isObj(meta.pareto) ? meta.pareto.y : undefined, "max");
}

const USAGE_NAMES: Record<string, string> = { usd: "cost", seconds: "time", calls: "calls" };

/**
 * Short axis name for a backend metric ref: `solved/value` → `solved`, `latency/p95` →
 * `latency p95`, `usage.usd` → `cost`, `usage.usd/solved` → `cost per solved`.
 */
export function refLabel(ref: string): string {
  if (ref.startsWith("usage.")) {
    const [field = "", per] = ref.slice("usage.".length).split("/");
    const name = USAGE_NAMES[field] ?? field.replace(/_/g, " ");
    return per ? `${name} per ${per}` : name;
  }
  return ref.replace(/\/value$/, "").replace(/\//g, " ");
}

const CURRENCY = new Set(["$", "£", "€"]);

/** Width used before layout is known (and in test DOMs). */
export const SCATTER_FALLBACK_W = 640;
/** Plot height for a plot `w` px wide: 9/16 of the width, 240 to 360 px. */
export const scatterHeight = (w: number): number => Math.round(Math.min(360, Math.max(240, w * 0.5625)));
const PL = 52;
const PR = 16;
const PT = 26;
const PB = 44;

const T = {
  tk: { fontSize: FS.tick, fill: "var(--ink-3)", fontVariantNumeric: "tabular-nums" },
  lbl: { fontSize: FS.label, fill: "var(--ink-2)" },
  lblB: { fontSize: FS.label, fill: "var(--ink)", fontWeight: 600 },
  lblBest: { fontSize: FS.label, fill: "var(--best)", fontWeight: 600 },
  lblS: { fontSize: FS.tick, fill: "var(--ink-3)" },
  axis: { stroke: "var(--ink-3)", strokeWidth: 1 },
  grid: { stroke: "var(--rule-2)", strokeWidth: 1 },
  whisk: { stroke: "var(--ink-3)", strokeWidth: 1.5, strokeLinecap: "round", fill: "none" },
  pareto: { stroke: "var(--ink)", strokeWidth: 1.4, fill: "none", strokeDasharray: "5 4" },
  seed: { fill: "var(--ink-3)", stroke: "var(--paper)", strokeWidth: 1.5 },
  reg: { fontSize: 10, fill: "var(--fail)" },
  key: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px 20px",
    marginTop: 14,
    fontSize: 13,
    color: "var(--ink-2)",
  },
  keyItem: { display: "inline-flex", alignItems: "center", gap: 7 },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

function meanStyle(best: boolean, dominated: boolean, regressed = false): CSSProperties {
  if (regressed) return { fill: "var(--fail)", stroke: "var(--paper)", strokeWidth: 2 };
  if (best) return { fill: "var(--best)", stroke: "var(--paper)", strokeWidth: 2 };
  if (dominated) return { fill: "var(--paper)", stroke: "var(--ink-3)", strokeWidth: 1.6 };
  return { fill: "var(--ink)", stroke: "var(--paper)", strokeWidth: 2 };
}

const range = (lo: number | null, hi: number | null) =>
  lo !== null && hi !== null ? ` [${fmtNum(lo)}, ${fmtNum(hi)}]` : "";

const REGRESSION_TIP = "regression vs best earlier version";

/** A number, or null for ordinal (text) values. */
const numeric = (v: number | string | null): number | null => (typeof v === "number" ? v : null);

/**
 * Scatter panel. Reads `meta.x_label`, `meta.y_label` (else the backend's refs `meta.x`,
 * `meta.y`), `meta.scale` (x axis), `meta.x_type` (`"ordinal"`: text x in row order),
 * `meta.pareto` (`{x, y}` directions; null or missing: no front), `meta.best_group` and
 * `meta.y_higher_is_better` (see `ScatterMeta`).
 */
export function ScatterPanel({ result }: { result: PanelResult }) {
  const [ref, W] = useElementWidth<HTMLDivElement>(SCATTER_FALLBACK_W);
  const rows = result.rows as unknown as ScatterRow[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  if (rows.length === 0) return <p style={T.empty}>No data</p>;
  const H = scatterHeight(W);
  const ordinal = meta.x_type === "ordinal";
  // A front exists only when the view sets Pareto directions on a numeric x; otherwise the
  // server marks every row `pareto: false`, which must not read as "dominated".
  const dirs = !ordinal && isObj(meta.pareto) ? meta.pareto : null;
  const hasFront = dirs !== null;
  const xDir = dirOf(dirs?.x, "min");
  const yDir = yDirOf(meta);
  const kind = meta.scale === "log" ? "log" : "linear";
  const label = (...keys: string[]) => {
    const hit = keys.map((k) => meta[k]).find((v) => typeof v === "string" && v !== "");
    return typeof hit === "string" ? hit : null;
  };
  const xLabel = label("x_label") ?? refLabel(label("x") ?? "x");
  const yLabel = label("y_label") ?? refLabel(label("y") ?? "y");
  const xUnit = typeof meta.x_unit === "string" ? meta.x_unit : "";
  const yUnit = typeof meta.y_unit === "string" ? meta.y_unit : typeof meta.unit === "string" ? meta.unit : "";
  const xTick = (v: number) => (CURRENCY.has(xUnit) ? withUnit(fmtTick(v), xUnit) : fmtTick(v));
  const yTick = (v: number) => (CURRENCY.has(yUnit) ? withUnit(fmtTick(v), yUnit) : fmtTick(v));
  const bestGroup =
    typeof meta.best_group === "string" || meta.best_group === null ? meta.best_group : undefined;
  const best = bestIndex(rows, yDir, bestGroup);

  const nums = (vs: (number | null)[]) => vs.filter((v): v is number => v !== null);
  const xs = ordinal
    ? []
    : rows.flatMap((r) =>
        nums([numeric(r.x), r.x_lo, r.x_hi, ...r.seeds.map((s) => numeric(s.x))]),
      );
  const ys = rows.flatMap((r) => nums([r.y, r.y_lo, r.y_hi, ...r.seeds.map((s) => s.y)]));
  // `meta.y_unit` (or `meta.unit`) and `meta.value_format` describe y; without them plain numbers
  const yFmt =
    yUnit || typeof meta.value_format === "string"
      ? valueFormatter({ unit: yUnit, value_format: meta.value_format }, ys, yLabel)
      : null;
  const yVal = (v: number) => (yFmt ? yFmt.value(v) : fmtNum(v));
  const yRange = (lo: number | null, hi: number | null) =>
    yFmt && lo !== null && hi !== null ? ` [${yFmt.num(lo)}, ${yFmt.value(hi)}]` : range(lo, hi);
  const { domain: xDom, ticks: xTicks } = xAxis(kind, xs);
  const X = xScale(kind, xDom, [PL, W - PR]);
  // ordinal: one equal band per row, in row order (the engine sorts versions naturally)
  const band = (W - PR - PL) / rows.length;
  const bandX = (i: number) => PL + (i + 0.5) * band;
  const yLo = Math.min(...ys);
  const yHi = Math.max(...ys);
  const ys0 = scaleLinear()
    .domain([yLo, yHi === yLo ? yLo + 1 : yHi])
    .nice(5);
  const Y = scaleLinear()
    .domain(ys0.domain())
    .range([H - PB, PT]);
  const yTicks = ys0.ticks(5);

  const front = !hasFront
    ? []
    : rows.flatMap((r) => (r.pareto && typeof r.x === "number" ? [{ x: r.x, y: r.y }] : []));
  const regressions = ordinal ? rows.filter((r) => r.regression).length : 0;
  const stairs = paretoPath(front, xDir, xDir === "min" ? xDom[1] : xDom[0]);
  const stairsD = stairs
    .map(([x, y], i) => `${i ? "L" : "M"}${X(x).toFixed(1)} ${Y(y).toFixed(1)}`)
    .join("");

  return (
    <div ref={ref}>
      <svg
        width={W}
        height={H}
        role="img"
        aria-label={
          hasFront
            ? `${xLabel} against ${yLabel}; ${front.length} of ${rows.length} on the Pareto front`
            : `${xLabel} against ${yLabel}`
        }
        style={{ display: "block", overflow: "visible", fontFamily: "var(--sans)" }}
      >
        <text x={PL} y={PT - 12} style={T.lblS}>
          {axisTitle(yLabel, yUnit, { unitOnTicks: CURRENCY.has(yUnit) })}
        </text>
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={PL} x2={W - PR} y1={Y(t)} y2={Y(t)} style={T.grid} />
            <text x={PL - 8} y={Y(t) + 4} textAnchor="end" style={T.tk}>
              {yTick(t)}
            </text>
          </g>
        ))}
        <line x1={PL} x2={W - PR} y1={H - PB} y2={H - PB} style={T.axis} />
        {ordinal
          ? rows.map((r, i) => (
              <g key={`x${r.group_id}`}>
                <line x1={bandX(i)} x2={bandX(i)} y1={H - PB} y2={H - PB + 4} style={T.axis} />
                <text
                  data-tick={String(r.x)}
                  x={bandX(i)}
                  y={H - PB + 17}
                  textAnchor="middle"
                  style={T.tk}
                >
                  {String(r.x)}
                </text>
              </g>
            ))
          : xTicks.map((t) => (
              <g key={`x${t}`}>
                <line x1={X(t)} x2={X(t)} y1={H - PB} y2={H - PB + 4} style={T.axis} />
                <text
                  data-tick={xTick(t)}
                  x={X(t)}
                  y={H - PB + 17}
                  textAnchor="middle"
                  style={T.tk}
                >
                  {xTick(t)}
                </text>
              </g>
            ))}
        <text x={W - PR} y={H - PB + 36} textAnchor="end" style={T.lblS}>
          {axisTitle(xLabel, xUnit, { log: kind === "log" && !ordinal, unitOnTicks: CURRENCY.has(xUnit) })}
        </text>
        {stairsD && <path data-testid="pareto" d={stairsD} style={T.pareto} />}
        {rows.map((r, i) => {
          const x = ordinal ? bandX(i) : X(Number(r.x));
          const y = Y(r.y);
          const isBest = i === best;
          const dominated = hasFront && !r.pareto;
          const regressed = ordinal && r.regression;
          const right = x + 12 + r.label.length * 7 <= W - PR;
          const xLine = ordinal
            ? `${xLabel} ${r.x}`
            : `${xLabel} ${withUnit(fmtNum(Number(r.x)), xUnit)}${range(r.x_lo, r.x_hi)}`;
          const status = regressed
            ? `, ${REGRESSION_TIP}`
            : hasFront
              ? `, ${r.pareto ? "on the Pareto front" : "dominated"}`
              : "";
          return (
            <g key={r.group_id} data-group={r.group_id}>
              {r.seeds.map((s, k) => (
                <circle
                  key={k}
                  data-seed=""
                  cx={ordinal ? x : X(Number(s.x))}
                  cy={Y(s.y)}
                  r={3.2}
                  style={T.seed}
                />
              ))}
              {r.y_lo !== null && r.y_hi !== null && (
                <path
                  data-testid="ywhisk"
                  d={`M${x} ${Y(r.y_lo)}V${Y(r.y_hi)}M${x - 4} ${Y(r.y_lo)}H${x + 4}M${x - 4} ${Y(r.y_hi)}H${x + 4}`}
                  style={{ ...T.whisk, ...(isBest ? { stroke: "var(--best)" } : {}) }}
                />
              )}
              {r.x_lo !== null && r.x_hi !== null && (
                <path
                  data-testid="xwhisk"
                  d={`M${X(r.x_lo)} ${y}H${X(r.x_hi)}M${X(r.x_lo)} ${y - 4}V${y + 4}M${X(r.x_hi)} ${y - 4}V${y + 4}`}
                  style={{ ...T.whisk, ...(isBest ? { stroke: "var(--best)" } : {}) }}
                />
              )}
              <rect
                data-testid="mean"
                data-pareto={r.pareto ? "true" : "false"}
                data-best={isBest ? "true" : "false"}
                data-regression={regressed ? "true" : "false"}
                x={x - 5}
                y={y - 5}
                width={10}
                height={10}
                rx={1.5}
                style={meanStyle(isBest, dominated, regressed)}
              />
              {regressed && (
                <g data-testid="regression">
                  <text x={x} y={y + 19} textAnchor="middle" style={T.reg}>
                    ▼
                  </text>
                  <title>{REGRESSION_TIP}</title>
                </g>
              )}
              <text
                x={right ? x + 12 : x - 12}
                y={y - 8}
                textAnchor={right ? "start" : "end"}
                style={isBest ? T.lblBest : dominated ? T.lbl : T.lblB}
              >
                {r.label}
              </text>
              <rect x={x - 14} y={y - 14} width={28} height={28} style={{ fill: "transparent" }}>
                <title>
                  {`${r.label}\n${yLabel} ${yVal(r.y)}${yRange(r.y_lo, r.y_hi)}\n` +
                    `${xLine}\n${r.seeds.length} seeds${status}`}
                </title>
              </rect>
            </g>
          );
        })}
      </svg>
      <div style={T.key} aria-label="Key">
        <span style={T.keyItem}>
          <svg width="12" height="16" aria-hidden="true">
            <path d="M6 1V15M2 1H10M2 15H10" style={T.whisk} />
            <rect x="2" y="4" width="8" height="8" rx="1.5" style={meanStyle(false, false)} />
          </svg>
          mean, 95% CI
        </span>
        <span style={T.keyItem}>
          <svg width="12" height="12" aria-hidden="true">
            <circle cx="6" cy="6" r="3.2" style={T.seed} />
          </svg>
          seed
        </span>
        {hasFront && (
          <span style={T.keyItem} title="No other group is better on both axes">
            <svg width="22" height="12" aria-hidden="true">
              <path d="M1 10H11V2H21" style={T.pareto} />
            </svg>
            Pareto
          </span>
        )}
        {hasFront && (
          <span style={T.keyItem} title="Another group is at least as good on both axes">
            <svg width="12" height="12" aria-hidden="true">
              <rect x="2" y="2" width="8" height="8" rx="1.5" style={meanStyle(false, true)} />
            </svg>
            dominated
          </span>
        )}
        {regressions > 0 && (
          <span
            style={T.keyItem}
            title="Worse than the best earlier version by more than that version's 95% CI"
          >
            <svg width="12" height="12" aria-hidden="true">
              <path d="M1 2H11L6 10Z" style={{ fill: "var(--fail)" }} />
            </svg>
            regression
          </span>
        )}
      </div>
    </div>
  );
}

export default ScatterPanel;
