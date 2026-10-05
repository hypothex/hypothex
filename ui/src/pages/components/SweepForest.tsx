/**
 * Panel b (mockup `drawSweepForest`): one row per scored cell, best first. Each row has
 * its seed dots, mean square, and 95% interval whisker; the best cell's interval is a
 * band behind every row, so a row inside the band is within noise of the best.
 */
import type { ReactElement } from "react";
import { AxisBottom, GridX } from "../../charts/Axis";
import { BestBand, IdenticalSeeds, MeanMark, SeedDots, Whisker } from "../../charts/Glyphs";
import { linear, niceDomain, tickFormat, useElementWidth } from "../../charts/Scale";
import { useTooltip } from "../../charts/Tooltip";
import { isNum } from "./format";
import { type SweepCellRow, cellLabel, cellTip, rankCells, sameParams } from "./SweepModel";

export interface SweepForestProps {
  cells: readonly SweepCellRow[];
  best: SweepCellRow | null;
  names: readonly string[];
  metric: string;
  /** Caption under the axis, e.g. `top1 v1`. */
  axisLabel: string;
  higherIsBetter: boolean;
  maxSeeds: number;
  seedsOf: (cell: SweepCellRow) => number[];
}

/** Label column width, row height, and top margin in px (mockup values). */
const LW = 96;
const ROW = 34;
const TOP = 22;

/** Two or more seeds that all gave one score: drawn as `◇×n` (spec: never stacked dots or a fake `± 0`). */
function identical(seeds: readonly number[]): boolean {
  return seeds.length > 1 && seeds.every((v) => v === seeds[0]);
}

/** Keep labels inside the chart; hover retains the full text, including long sampled params. */
function ForestLabel({ text, y, kind }: { text: string; y: number; kind: "lbl" | "lbl-b" | "lbl-s" }): ReactElement {
  return (
    <foreignObject className="forest-label" x={0} y={y} width={LW - 12} height={ROW}>
      <div className={kind} title={text} style={{
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right",
        fontFamily: "var(--sans)", color: kind === "lbl-b" ? "var(--ink)" : kind === "lbl-s" ? "var(--ink-3)" : "var(--ink-2)",
        lineHeight: `${ROW}px`,
      }}>{text}</div>
    </foreignObject>
  );
}

export function SweepForest({
  cells,
  best,
  names,
  metric,
  axisLabel,
  higherIsBetter,
  maxSeeds,
  seedsOf,
}: SweepForestProps): ReactElement {
  const [ref, width] = useElementWidth<HTMLDivElement>(380);
  const tip = useTooltip();
  const rows = rankCells(cells, higherIsBetter);
  if (rows.length === 0) return <p className="panel-empty">No scored runs yet</p>;
  const values = rows.flatMap((c) => [c.mean, c.lo, c.hi, ...seedsOf(c)]).filter(isNum);
  const x = linear(niceDomain(values), LW, Math.max(LW + 40, width - 8), 4);
  const fmt = tickFormat(x.ticks);
  const yAx = TOP + rows.length * ROW + 4;
  const isBest = (c: SweepCellRow): boolean => best !== null && sameParams(c.params, best.params);
  return (
    <div ref={ref} className="forest">
      <svg
        className="hx-chart"
        width={width}
        height={yAx + 42}
        role="img"
        aria-label={`Cells sorted by mean ${metric}, with seed dots and 95% intervals`}
      >
        <ForestLabel text={names.join(", ")} y={-12} kind="lbl-s" />
        <GridX x={x.at} ticks={x.ticks} y0={TOP} y1={yAx} />
        {best !== null && best.lo !== null && best.hi !== null ? (
          <BestBand x1={x.at(best.lo)} x2={x.at(best.hi)} y0={TOP} y1={yAx} />
        ) : null}
        {rows.map((c, i) => {
          const y = TOP + i * ROW + ROW / 2;
          const b = isBest(c);
          const seeds = seedsOf(c);
          const label = cellLabel(c.params, names);
          return (
            <g key={label} className="frow" data-label={label}>
              <ForestLabel text={label} y={y - ROW / 2} kind={b ? "lbl-b" : "lbl"} />
              {c.lo !== null && c.hi !== null ? <Whisker x1={x.at(c.lo)} x2={x.at(c.hi)} y={y} best={b} /> : null}
              {identical(seeds) ? (
                <IdenticalSeeds cx={x.at(seeds[0] ?? 0)} cy={y - 9} n={seeds.length} r={3.5} best={b} />
              ) : (
                <SeedDots x={x.at} values={seeds} y={y - 9} r={3} />
              )}
              <MeanMark cx={x.at(c.mean ?? 0)} cy={y} r={4.2} best={b} />
              {c.n < maxSeeds ? (
                <text className="lbl-s" x={x.at(c.hi ?? c.mean ?? 0) + 8} y={y + 4}>
                  {`n=${c.n}`}
                </text>
              ) : null}
              <rect
                className="hit"
                x={LW}
                y={y - ROW / 2}
                width={Math.max(0, width - LW)}
                height={ROW}
                tabIndex={0}
                {...tip.bind(cellTip(c, names, seeds))}
              />
            </g>
          );
        })}
        <AxisBottom x={x.at} ticks={x.ticks} y={yAx} x0={LW} x1={width} format={fmt} label={axisLabel} />
      </svg>
      {tip.node}
    </div>
  );
}
