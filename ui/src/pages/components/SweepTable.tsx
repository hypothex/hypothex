/**
 * Panel a when the heat table does not fit (one param, more than two, or sampled ranges):
 * one row per param combination, sortable by any param, `n` or the metric. Default order
 * is best first in the metric's direction; unscored cells stay last.
 */
import { type ReactElement, useState } from "react";
import type { RunStatus } from "../../api/models";
import { DASH, fmtInterval, fmtScore } from "./format";
import { SweepRunList } from "./SweepGlyphs";
import {
  type RunGlyphState,
  type SortState,
  type SweepCellRow,
  SORT_MEAN,
  SORT_N,
  defaultSort,
  nextSort,
  sameParams,
  sortCells,
} from "./SweepModel";

export interface SweepTableProps {
  names: readonly string[];
  cells: readonly SweepCellRow[];
  best: SweepCellRow | null;
  metric: string;
  higherIsBetter: boolean;
  maxSeeds: number;
  stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState;
}

export function SweepTable({
  names,
  cells,
  best,
  metric,
  higherIsBetter,
  maxSeeds,
  stateOf,
}: SweepTableProps): ReactElement {
  // null until the user clicks a header: the default then follows `higherIsBetter`, which
  // the sweep page only learns when the task leaderboard arrives after the first render
  const [chosen, setChosen] = useState<SortState | null>(null);
  const sort = chosen ?? defaultSort(higherIsBetter);
  const rows = sortCells(cells, sort);
  const header = (key: string, label: string, numeric: boolean): ReactElement => {
    const active = sort.key === key;
    return (
      <th
        key={key}
        className={numeric ? "r" : undefined}
        aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
      >
        <button
          type="button"
          title={`Sort by ${label}`}
          onClick={() => setChosen(nextSort(sort, key, higherIsBetter))}
        >
          {label}
          {active ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
        </button>
      </th>
    );
  };
  return (
    <table className="sw-table" aria-label={`Mean ${metric} by ${names.join(", ")}`}>
      <thead>
        <tr>
          {names.map((n) => header(n, n, false))}
          {header(SORT_N, "n", true)}
          {header(SORT_MEAN, metric, true)}
          <th className="r">95% CI</th>
          <th>runs</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((cell) => {
          const isBest = best !== null && sameParams(cell.params, best.params);
          return (
            <tr key={names.map((n) => cell.params[n] ?? "").join("\u0000")} className={isBest ? "best" : undefined}>
              {names.map((n) => (
                <td key={n}>{cell.params[n] ?? DASH}</td>
              ))}
              <td className="r" title={cell.n < maxSeeds ? `${cell.n} of ${maxSeeds} seeds scored` : undefined}>
                {cell.n}
              </td>
              <td className="r">
                {isBest ? (
                  <span className="bm" title="best">
                    ◆{" "}
                  </span>
                ) : null}
                {fmtScore(cell.mean)}
              </td>
              <td className="r">{cell.lo !== null && cell.hi !== null ? fmtInterval(cell.lo, cell.hi) : DASH}</td>
              <td>
                <SweepRunList runs={cell.runs} stateOf={stateOf} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
