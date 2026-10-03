/**
 * `leaderboard` panel: a forest plot with one row per seed group.
 *
 * Shows both kinds of noise: per-seed dots (identical seeds collapse to a diamond
 * with `×n`) and the test-set 95% interval as a whisker; a group with no test-set
 * interval (e.g. benchmarks, training runs) gets its seed t-interval. The best group's interval
 * is a band behind every row; the last column says how each row compares to it.
 */
import type { ReactElement } from "react";
import { AxisBottom, GridX } from "../charts/Axis";
import {
  BestBand,
  IdenticalSeeds,
  Key,
  KeyGlyph,
  MeanMark,
  SeedDots,
  Whisker,
  type KeyItem,
} from "../charts/Glyphs";
import {
  f4,
  fmtP,
  linear,
  niceDomain,
  signed,
  tickFormat,
  useElementWidth,
  type LinearScale,
} from "../charts/Scale";
import { useTooltip, type Tooltip } from "../charts/Tooltip";
import { fmtDuration, valueFormatter, type ValueFormatter } from "../charts/valueFormat";
import type { LeaderboardRow, NoiseInterval, Stats, UsageTotals, VersusBest } from "../api/models";
import type { PanelProps } from "./index";

/** `hypothex.core.seeds.Stats` as JSON. */
export type StatsJson = Stats;
/** `hypothex.core.leaderboard.NoiseInterval` as JSON. */
export type NoiseIntervalJson = NoiseInterval;
/** `hypothex.core.leaderboard.VersusBest` as JSON. */
export type VersusBestJson = VersusBest;
/** `hypothex.core.records.UsageTotals` as JSON. */
export type UsageJson = UsageTotals;
/** `hypothex.core.leaderboard.LeaderboardRow` as JSON (the fields this panel reads). */
export type LeaderboardRowJson = Omit<LeaderboardRow, "config_hash" | "within_noise_of_best">;

/** An interval drawn as the best band. */
export interface Band {
  lo: number;
  hi: number;
  /** Tooltip wording of the method, e.g. `Wilson, n = 180`. */
  how: string;
}

/** The vs-best verdict of one row. */
export interface Verdict {
  kind: "best" | "band" | "behind" | "none";
  text: string;
  p: string;
  tip: string;
}

/** Row height in px; the plot SVG of each row is exactly this tall. */
export const ROW_H = 104;
/** y of the seed marks inside a row. */
export const SEED_Y = 30;
/** y of the interval whisker inside a row. */
export const CI_Y = 58;
/** Plot width used before layout is known. */
export const PLOT_FALLBACK_W = 600;
const PAD = 8;

/**
 * Find the score key of the primary metric.
 *
 * Uses `meta.primary` when it names a score key (`accuracy` also matches
 * `accuracy/value`); otherwise the key whose stats equal a row's `primary`.
 */
export function primaryKey(
  rows: LeaderboardRowJson[],
  meta: Record<string, unknown> | undefined,
): string | null {
  const keys = new Set(rows.flatMap((r) => Object.keys(r.scores)));
  const hinted = meta?.primary;
  if (typeof hinted === "string") {
    if (keys.has(hinted)) return hinted;
    if (keys.has(`${hinted}/value`)) return `${hinted}/value`;
  }
  for (const r of rows) {
    const p = r.primary;
    if (!p) continue;
    const hit = Object.entries(r.scores).find(
      ([, s]) => s.mean === p.mean && s.std === p.std && s.n === p.n,
    );
    if (hit) return hit[0];
  }
  return [...keys].sort()[0] ?? null;
}

/**
 * The Examples page comparing run `a` with run `b` on `metric` (`name` or `name@version`);
 * the same URL as `hrefs.examples` (Task 23), built here because panels use plain links.
 */
export function examplesHref(a: string, b: string, metric: string): string {
  return `/x/${encodeURIComponent(a)}/${encodeURIComponent(b)}?metric=${encodeURIComponent(metric)}`;
}

/** Short column label for a score key: `accuracy/value` → `accuracy`, `lat/p95` → `lat p95`. */
export function metricLabel(key: string): string {
  return key.replace(/\/value$/, "").replace("/", " ");
}

/** The best group's band: its test-set interval, else its seed t-interval. */
export function bestBand(best: LeaderboardRowJson | null): Band | null {
  if (!best) return null;
  const t = best.test_interval;
  if (t) return { lo: t.lo, hi: t.hi, how: `${t.method === "wilson" ? "Wilson" : "bootstrap"}, n = ${t.n}` };
  const p = best.primary;
  if (p && p.ci_low != null && p.ci_high != null) {
    return { lo: p.ci_low, hi: p.ci_high, how: `t-interval over ${p.n} seeds` };
  }
  return null;
}

/** The whisker interval of one row. */
export interface RowInterval {
  lo: number;
  hi: number;
  /** `test`: test-set interval; `seed`: t-interval over seeds. */
  kind: "test" | "seed";
  /** Short name: `test-set 95% CI` or `95% CI`. */
  name: string;
  /** Method, e.g. `Wilson, n = 180` or `t-interval over 3 seeds`. */
  how: string;
}

/**
 * The interval drawn as a row's whisker: the test-set interval when shown, else the
 * t-interval over seeds when seeds are shown and differ.
 */
export function rowInterval(
  row: LeaderboardRowJson,
  showTest: boolean,
  showSeeds: boolean,
): RowInterval | null {
  const t = row.test_interval;
  if (showTest && t) {
    return {
      lo: t.lo,
      hi: t.hi,
      kind: "test",
      name: "test-set 95% CI",
      how: `${t.method === "wilson" ? "Wilson" : "bootstrap"}, n = ${t.n}`,
    };
  }
  const p = row.primary;
  if (!showSeeds || !p || row.identical_seeds || p.n < 2) return null;
  if (p.ci_low == null || p.ci_high == null || !Number.isFinite(p.ci_low) || !Number.isFinite(p.ci_high)) {
    return null;
  }
  return { lo: p.ci_low, hi: p.ci_high, kind: "seed", name: "95% CI", how: `t-interval over ${p.n} seeds` };
}

function testTip(v: VersusBestJson | null): string {
  if (!v || v.p == null) return "";
  const p = v.p < 0.001 ? "p < 0.001" : `p = ${fmtP(v.p)}`;
  let line = `${p}.`;
  if (v.test === "sign") {
    line = `Exact sign test on ${(v.fixed ?? 0) + (v.broken ?? 0)} changed examples (${v.fixed ?? 0} fixed / ${v.broken ?? 0} broken), ${p}.`;
  } else if (v.test === "paired_bootstrap") {
    line = `Paired bootstrap over examples, ${p}.`;
  } else if (v.test === "welch") {
    line = `Welch t-test over seeds, ${p}.`;
  }
  const need = v.examples_needed != null ? ` ≈${v.examples_needed} examples for p < 0.05.` : "";
  return ` ${line}${need}`;
}

/** How a row compares with the best row and its band. */
export function verdictOf(
  row: LeaderboardRowJson,
  best: LeaderboardRowJson | null,
  band: Band | null,
  fmt?: ValueFormatter,
): Verdict {
  if (row === best) {
    return { kind: "best", text: "best", p: "", tip: "Best mean. Its 95% CI is the green band." };
  }
  if (!row.primary || !best?.primary) {
    return { kind: "none", text: "—", p: "", tip: "No score for the primary metric." };
  }
  const m = row.primary.mean;
  const inBand = band !== null && m >= Math.min(band.lo, band.hi) && m <= Math.max(band.lo, band.hi);
  const p = row.vs_best?.p != null ? `p ${fmtP(row.vs_best.p)}` : "";
  const base = band
    ? inBand
      ? "Mean inside the best's 95% CI: not proven worse."
      : "Mean outside the best's 95% CI."
    : "No 95% CI for the best group.";
  return {
    kind: inBand ? "band" : "behind",
    text: fmt ? fmt.delta(m, best.primary.mean) : signed(m - best.primary.mean, 3),
    p,
    tip: base + testTip(row.vs_best),
  };
}

function Who({ by }: { by: string[] }): ReactElement {
  const first = by[0] ?? "unknown";
  const kind = first.startsWith("agent") ? "agent" : "human";
  return (
    <span className={`who ${kind}`}>
      <i />
      {by.length ? by.join(", ") : "unknown"}
    </span>
  );
}

function SeedSpread({ row, fmt }: { row: LeaderboardRowJson; fmt: ValueFormatter }): ReactElement | null {
  const s = row.primary;
  if (!s) return null;
  if (row.identical_seeds) {
    return (
      <span className="hint" title={`${s.n} seeds, one score: the model ignores the seed`}>
        <KeyGlyph kind="identical" />×{s.n}
      </span>
    );
  }
  if (s.n <= 1) {
    return (
      <span className="hint" title="One run: no seed noise estimate">
        single seed
      </span>
    );
  }
  return <span title={`std over ${s.n} seeds`}>± {fmt.spread(s.std)}</span>;
}

interface PlotProps {
  row: LeaderboardRowJson;
  pkey: string;
  x: LinearScale;
  width: number;
  band: Band | null;
  best: LeaderboardRowJson | null;
  showSeeds: boolean;
  showTest: boolean;
  tip: Tooltip;
  fmt: ValueFormatter;
}

function RowPlot({ row, pkey, x, width, band, best, showSeeds, showTest, tip, fmt }: PlotProps): ReactElement {
  const s = row.primary;
  const isBest = row === best;
  const seeds = row.seed_values[pkey] ?? [];
  const t = rowInterval(row, showTest, showSeeds);
  return (
    <svg
      className="hx-chart"
      width={width}
      height={ROW_H}
      role="img"
      aria-label={`${row.label}: ${s ? fmt.value(s.mean) : "no score"}`}
    >
      <GridX x={x.at} ticks={x.ticks} y0={0} y1={ROW_H} />
      {band ? <BestBand x1={x.at(band.lo)} x2={x.at(band.hi)} y0={0} y1={ROW_H} /> : null}
      {best?.primary ? (
        <line
          className="bestline"
          x1={x.at(best.primary.mean)}
          x2={x.at(best.primary.mean)}
          y1={0}
          y2={ROW_H}
        />
      ) : null}
      {s && showSeeds ? (
        <g
          {...tip.bind(
            row.identical_seeds
              ? `${row.label}\n×${s.n}: all seeds gave ${fmt.value(s.mean)}`
              : `${row.label}\nseeds: ${seeds.map(fmt.value).join(", ")}`,
          )}
        >
          {row.identical_seeds ? (
            <IdenticalSeeds cx={x.at(s.mean)} cy={SEED_Y} n={s.n} best={isBest} />
          ) : (
            <SeedDots x={x.at} values={seeds} y={SEED_Y} />
          )}
          <rect className="hit" x={x.at(s.mean) - 40} y={SEED_Y - 14} width={80} height={24} />
        </g>
      ) : null}
      {s && t ? (
        <g
          {...tip.bind(
            `${row.label}\nmean ${fmt.value(s.mean)}\n${t.name} ${fmt.num(t.lo)}–${fmt.value(t.hi)}\n(${t.how})`,
          )}
        >
          <Whisker x1={x.at(t.lo)} x2={x.at(t.hi)} y={CI_Y} best={isBest} />
          <rect
            className="hit"
            x={x.at(t.lo)}
            y={CI_Y - 10}
            width={Math.max(8, x.at(t.hi) - x.at(t.lo))}
            height={20}
          />
        </g>
      ) : null}
      {s ? <MeanMark cx={x.at(s.mean)} cy={CI_Y} best={isBest} /> : null}
    </svg>
  );
}

/** Draw a `leaderboard` panel result. */
export function Leaderboard({ result }: PanelProps): ReactElement {
  const rows = result.rows as unknown as LeaderboardRowJson[];
  const [plotRef, width] = useElementWidth<HTMLDivElement>(PLOT_FALLBACK_W);
  const tip = useTooltip();
  if (rows.length === 0) return <p className="panel-empty">No scored runs yet</p>;

  const meta = result.meta;
  const noise = Array.isArray(meta?.noise) ? (meta.noise as string[]) : ["seed", "test_set"];
  const showSeeds = noise.includes("seed");
  const showTest = noise.includes("test_set");
  const pkey = primaryKey(rows, meta) ?? "";
  const secondKey = [...new Set(rows.flatMap((r) => Object.keys(r.scores)))]
    .sort()
    .find((k) => k !== pkey);
  const best = rows.find((r) => r.primary && r.vs_best == null) ?? null;
  const band = bestBand(best);
  const fmt = valueFormatter(meta, rows.flatMap((r) => (r.primary ? [r.primary.mean] : [])), pkey);
  const fmt2 = valueFormatter(
    // the unit and format describe the primary metric, not the second column
    undefined,
    rows.flatMap((r) => (secondKey && r.scores[secondKey] ? [r.scores[secondKey].mean] : [])),
    secondKey ?? "",
  );
  const unitTip = fmt.unit ? ` (${fmt.unit})` : "";

  const values: number[] = [];
  for (const r of rows) {
    if (!r.primary) continue;
    values.push(r.primary.mean);
    if (showSeeds) values.push(...(r.seed_values[pkey] ?? []));
    const ci = rowInterval(r, showTest, showSeeds);
    if (ci) values.push(ci.lo, ci.hi);
  }
  if (band) values.push(band.lo, band.hi);
  const x = linear(niceDomain(values), PAD, width - PAD);
  const plotHead = showSeeds && showTest ? "seeds, 95% CI" : showSeeds ? "seeds" : "95% CI";
  const keyItems: KeyItem[] = [];
  if (showSeeds) {
    keyItems.push({ glyph: "seed", label: "seed" });
    if (rows.some((r) => r.identical_seeds)) {
      keyItems.push({ glyph: "identical", label: "identical seeds", title: "All seeds gave one score" });
    }
  }
  const kinds = new Set(rows.map((r) => rowInterval(r, showTest, showSeeds)?.kind));
  if (kinds.has("test")) {
    keyItems.push({ glyph: "whisker", label: "test-set 95% CI" });
  }
  if (kinds.has("seed")) {
    keyItems.push({ glyph: "whisker", label: "95% CI", title: "t-interval over seeds" });
  }
  if (band) keyItems.push({ glyph: "band", label: "best's CI", title: band.how });

  return (
    <div className="lb">
      <div className="forest">
        <div className="frow head">
          <div>Idea</div>
          <div className="acc" title={`${pkey}${unitTip}`}>
            {metricLabel(pkey)}
            {fmt.unit ? ` ${fmt.unit}` : ""}
          </div>
          <div ref={plotRef}>{plotHead}</div>
          <div className="f1 hd" title={secondKey ?? ""}>
            {secondKey ? metricLabel(secondKey) : ""}
          </div>
          <div>vs best</div>
        </div>
        {rows.map((row, i) => {
          const v = verdictOf(row, best, band, fmt);
          const s = row.primary;
          const second = secondKey ? row.scores[secondKey] : undefined;
          const u = row.usage;
          const ci = rowInterval(row, showTest, showSeeds);
          return (
            <div className="frow" data-row={i} key={row.group_id}>
              <div>
                <div className="nm" title={row.hypothesis}>
                  {row.label}
                </div>
                <div className="meta">
                  <Who by={row.created_by} />
                  <span>
                    <a href={`/r/${encodeURIComponent(row.latest_run_id)}`}>{row.group_id}</a>
                  </span>
                  {u && (u.usd > 0 || u.seconds > 0) ? (
                    <span title={`${u.calls} calls, ${u.tokens_in} tokens in, ${u.tokens_out} out`}>
                      ${u.usd.toFixed(2)} · {fmtDuration(u.seconds)}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="acc">
                <div className="big" title={s ? fmt.value(s.mean) : undefined}>
                  {s ? fmt.num(s.mean) : "—"}
                </div>
                <div className="sd">
                  <SeedSpread row={row} fmt={fmt} />
                </div>
                {ci ? (
                  <div className="sd">
                    <span title={`${ci.name} (${ci.how})`}>
                      {fmt.bound(ci.lo)}–{fmt.bound(ci.hi)}
                    </span>
                  </div>
                ) : null}
              </div>
              <div className="fplot">
                <RowPlot
                  row={row}
                  pkey={pkey}
                  x={x}
                  width={width}
                  band={band}
                  best={best}
                  showSeeds={showSeeds}
                  showTest={showTest}
                  tip={tip}
                  fmt={fmt}
                />
              </div>
              <div className="f1">{second ? fmt2.value(second.mean) : ""}</div>
              <div className="vd" title={v.tip}>
                {v.kind === "none" ? null : <span className={`vg ${v.kind}`} />}
                {best && row !== best && s && pkey ? (
                  <a className="vx" href={examplesHref(row.latest_run_id, best.latest_run_id, pkey.split("/")[0] ?? pkey)}>
                    {v.text}
                  </a>
                ) : (
                  <span>{v.text}</span>
                )}
                {v.p ? <small>{v.p}</small> : null}
              </div>
            </div>
          );
        })}
        <div className="frow axisrow">
          <div />
          <div />
          <div className="fplot">
            <svg className="hx-chart" width={width} height={48} aria-hidden="true">
              {band ? <BestBand x1={x.at(band.lo)} x2={x.at(band.hi)} y0={0} y1={8} /> : null}
              <AxisBottom
                x={x.at}
                ticks={x.ticks}
                y={8}
                x0={0}
                x1={width}
                format={tickFormat(x.ticks)}
                label={fmt.unit ? `${metricLabel(pkey)}, ${fmt.unit}` : metricLabel(pkey)}
              />
            </svg>
          </div>
          <div />
          <div />
        </div>
      </div>
      {keyItems.length ? <Key items={keyItems} /> : null}
      {tip.node}
    </div>
  );
}
