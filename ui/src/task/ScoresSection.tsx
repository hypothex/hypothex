/**
 * Scores section (spec 4.2): the primary metric as dot + 95% CI + seed dots per visible
 * identity on one axis with the best interval as a band; for training kinds also the
 * score against GPU-hours with the Pareto front. Seed dots are always drawn (principle 6);
 * a row without an interval gets `DotCIChart`'s own "no interval" tooltip note.
 */
import type { ReactElement } from "react";
import type { TaskRuns } from "../api/models";
import { type DotCIRow, DotCIChart } from "../charts/DotCIChart";
import { Fit } from "../charts/Fit";
import { type ScatterPoint, ScatterPareto } from "../charts/ScatterPareto";
import { Panel } from "../chrome/Panel";
import { PanelSection } from "../chrome/PanelSection";
import { matchesSearch } from "./stepMetrics";
import { type Identity, keyLabel } from "./useRunSelection";

/** One dot + interval row per identity, in list order. */
export function scoreRows(items: readonly Identity[], colorOf: (id: string) => string): DotCIRow[] {
  return items.map((i) => {
    const g = i.kind === "group" ? i.group : null;
    return {
      id: i.id,
      name: i.name,
      color: colorOf(i.id),
      mean: i.value,
      lo: g?.test_interval?.lo ?? g?.primary?.ci_low ?? null,
      hi: g?.test_interval?.hi ?? g?.primary?.ci_high ?? null,
      seeds: g ? g.seed_values : [],
      n: g?.primary?.n ?? (i.value === null ? 0 : 1),
      best: g?.is_best === true,
    };
  });
}

/** The best config's test-set interval, drawn as a band behind every row. */
export function bestBand(data: TaskRuns): { lo: number; hi: number } | null {
  const best = data.groups.find((g) => g.is_best);
  return best?.test_interval ? { lo: best.test_interval.lo, hi: best.test_interval.hi } : null;
}

/** Mean GPU-hours per run (x) against the primary (y), for identities with both. */
export function paretoPoints(items: readonly Identity[], colorOf: (id: string) => string): ScatterPoint[] {
  return items.flatMap((i): ScatterPoint[] => {
    const hours = i.runs.map((r) => r.gpu_hours).filter((h): h is number => typeof h === "number" && Number.isFinite(h));
    if (i.value === null || hours.length === 0) return [];
    const g = i.kind === "group" ? i.group : null;
    return [
      {
        id: i.id,
        name: i.name,
        color: colorOf(i.id),
        x: hours.reduce((a, b) => a + b, 0) / hours.length,
        y: i.value,
        yLo: g?.test_interval?.lo ?? null,
        yHi: g?.test_interval?.hi ?? null,
      },
    ];
  });
}

export interface ScoresSectionProps {
  data: TaskRuns;
  items: readonly Identity[];
  colorOf: (id: string) => string;
  highlight: string | null;
  query: string;
}

export function ScoresSection({ data, items, colorOf, highlight, query }: ScoresSectionProps): ReactElement | null {
  const title = keyLabel(data.primary);
  const paretoTitle = `${title} vs GPU-hours`;
  const points = data.kind === "training" ? paretoPoints(items, colorOf) : [];
  const showScore = matchesSearch(title, query);
  const showPareto = points.length > 0 && matchesSearch(paretoTitle, query);
  if (!showScore && !showPareto) return null;
  const rows = scoreRows(items, colorOf);
  const what = items.some((i) => i.kind === "run") ? "runs" : "configs";
  return (
    <PanelSection title="Scores" count={(showScore ? 1 : 0) + (showPareto ? 1 : 0)} storageKey={`${data.project}/${data.task}`} grid="fill">
      {showScore ? (
        <Panel title={title} unit={data.higher_is_better ? "higher is better" : "lower is better"} aside={`${rows.length} ${what}`}>
          <Fit>{(width) => <DotCIChart width={width} rows={rows} band={bestBand(data)} highlight={highlight} />}</Fit>
        </Panel>
      ) : null}
      {showPareto ? (
        <Panel title={paretoTitle} unit="Pareto front dashed">
          <Fit>
            {(width) => <ScatterPareto width={width} points={points} xName="GPU-hours per run" yName={title} higherIsBetter={data.higher_is_better} />}
          </Fit>
        </Panel>
      ) : null}
    </PanelSection>
  );
}
