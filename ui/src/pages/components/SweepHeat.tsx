/**
 * Panel a for a two-param sweep (spec 8A.6): mean primary metric per row × column param.
 * Darker = better (in the metric's direction); the best cell is ringed and marked. The
 * exact numbers (seeds, 95% interval, seed σ) live in each value's tooltip.
 */
import type { CSSProperties, ReactElement } from "react";
import type { RunStatus } from "../../api/models";
import { fmtInterval, fmtScore, isNum } from "./format";
import { RunGlyph, SweepRunList } from "./SweepGlyphs";
import {
  type HeatAxes,
  type RunGlyphState,
  type SweepCellRow,
  cellTip,
  heatLevel,
  heatPercent,
  meanOf,
  sameParams,
} from "./SweepModel";

export interface SweepHeatProps {
  axes: HeatAxes;
  cells: readonly SweepCellRow[];
  best: SweepCellRow | null;
  /** Short metric name, e.g. `top1`. */
  metric: string;
  higherIsBetter: boolean;
  /** Seeds per cell in the sweep; cells with fewer scored seeds show `n=k`. */
  maxSeeds: number;
  stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState;
  seedsOf: (cell: SweepCellRow) => number[];
}

const KEY_STATES: readonly RunGlyphState[] = ["finished", "running", "queued", "failed"];
const RAMP: readonly number[] = [0, 0.25, 0.5, 0.75, 1];

const heatStyle = (pct: number): CSSProperties => ({ "--heat": `${pct}%` }) as CSSProperties;

interface HeatCellProps {
  id: string;
  cell: SweepCellRow | undefined;
  isBest: boolean;
  level: number;
  maxSeeds: number;
  names: readonly string[];
  seeds: number[];
  stateOf: SweepHeatProps["stateOf"];
}

function HeatCell({ id, cell, isBest, level, maxSeeds, names, seeds, stateOf }: HeatCellProps): ReactElement {
  if (cell === undefined) {
    return (
      <td className="c empty" data-testid={`cell-${id}`}>
        <span className="v">·</span>
      </td>
    );
  }
  const scored = cell.mean !== null;
  const pct = heatPercent(level);
  return (
    <td
      className={`c${scored ? "" : " empty"}${isBest ? " best" : ""}`}
      style={scored ? heatStyle(pct) : undefined}
      data-heat={scored ? pct : undefined}
      data-testid={`cell-${id}`}
    >
      {isBest ? <span className="bm">◆ best</span> : null}
      <span className="v" title={cellTip(cell, names, seeds)}>
        {scored ? fmtScore(cell.mean) : "·"}
        {(scored && cell.n < maxSeeds) || cell.uncounted ? <small>{`n=${cell.n}${cell.uncounted ? ` +${cell.uncounted}` : ""}`}</small> : null}
      </span>
      <SweepRunList runs={cell.runs} stateOf={stateOf} />
    </td>
  );
}

export function SweepHeat({
  axes,
  cells,
  best,
  metric,
  higherIsBetter,
  maxSeeds,
  stateOf,
  seedsOf,
}: SweepHeatProps): ReactElement {
  const names = [axes.row, axes.col];
  const at = (r: string, c: string): SweepCellRow | undefined =>
    cells.find((x) => x.params[axes.row] === r && x.params[axes.col] === c);
  const means = cells.map((x) => x.mean).filter(isNum);
  const lo = means.length > 0 ? Math.min(...means) : null;
  const hi = means.length > 0 ? Math.max(...means) : null;
  const level = (cell: SweepCellRow | undefined): number => {
    const mean = cell?.mean ?? null;
    return mean !== null && lo !== null && hi !== null ? heatLevel(mean, lo, hi, higherIsBetter) : 0;
  };
  const usedStates = new Set(cells.flatMap((x) => x.runs.map((r) => stateOf(r.run_id, r.status))));
  const extraStates = (["lost", "killed", "stale"] as const).filter((s) => usedStates.has(s));
  return (
    <>
      <table className="heat" aria-label={`Mean ${metric} by ${axes.row} and ${axes.col}`}>
        <thead>
          <tr>
            <th className="cor" scope="col">{`${axes.row} \\ ${axes.col}`}</th>
            {axes.cols.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
            <th className="mh" scope="col" title={`Mean over ${axes.col}`}>
              mean
            </th>
          </tr>
        </thead>
        <tbody>
          {axes.rows.map((r) => (
            <tr key={r}>
              <th className="rh" scope="row">
                {r}
              </th>
              {axes.cols.map((c) => {
                const cell = at(r, c);
                return (
                  <HeatCell
                    key={c}
                    id={`${r}|${c}`}
                    cell={cell}
                    isBest={cell !== undefined && best !== null && sameParams(cell.params, best.params)}
                    level={level(cell)}
                    maxSeeds={maxSeeds}
                    names={names}
                    seeds={cell ? seedsOf(cell) : []}
                    stateOf={stateOf}
                  />
                );
              })}
              <td className="m rm" title={`Mean over ${axes.col} at ${axes.row} ${r}`}>
                {fmtScore(meanOf(axes.cols.map((c) => at(r, c)?.mean ?? null)))}
              </td>
            </tr>
          ))}
          <tr>
            <th className="rh mh" scope="row" title={`Mean over ${axes.row}`}>
              mean
            </th>
            {axes.cols.map((c) => (
              <td key={c} className="m" title={`Mean over ${axes.row} at ${axes.col} ${c}`}>
                {fmtScore(meanOf(axes.rows.map((r) => at(r, c)?.mean ?? null)))}
              </td>
            ))}
            <td />
          </tr>
        </tbody>
      </table>
      <div className="key" role="group" aria-label="Key">
        {lo !== null && hi !== null ? (
          <span title="Darker is better">
            <span className="ramp">
              {RAMP.map((t) => (
                <i key={t} style={heatStyle(heatPercent(t))} />
              ))}
            </span>
            {fmtInterval(lo, hi)}
          </span>
        ) : null}
        {best !== null ? (
          <span className="best-k">
            <b aria-hidden="true">◆</b>
            <span>{`best, ${best.n} seed${best.n === 1 ? "" : "s"}`}</span>
          </span>
        ) : null}
        {KEY_STATES.map((s) => (
          <span key={s} className="st-k">
            <RunGlyph state={s} />
            {s}
          </span>
        ))}
        {extraStates.map((s) => (
          <span key={s} className="st-k" title={s === "stale" ? "Host not reachable; the run may still be going" : undefined}>
            <RunGlyph state={s} />
            {s}
          </span>
        ))}
      </div>
    </>
  );
}
