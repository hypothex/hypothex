/**
 * Score keys (spec 4.2, eval tasks): keys split as `<prefix>/<A>.<B>.<metric>` into one
 * section per metric (`sectionsFromKeys`; the primary's section first and open, others
 * closed, so 50+ keys stay fast) and one horizontal bar panel per key: bars from zero in
 * run colours, the best value of that key green (`rowBest`), CI whiskers on the primary
 * key. Panel search matches titles and keys.
 */
import type { ReactElement } from "react";
import type { TaskRuns } from "../api/models";
import { type BarRow, BarPanel } from "../charts/BarPanel";
import { Fit } from "../charts/Fit";
import { Panel } from "../chrome/Panel";
import { PanelSection } from "../chrome/PanelSection";
import { type KeySection, sectionsFromKeys } from "../lib/scoreKeys";
import { rowBest } from "./compareModel";
import { matchesSearch } from "./stepMetrics";
import { type Identity, scoreOf } from "./useRunSelection";

/** Key sections with the panels the search shows (the primary panel first); empty sections dropped. */
export function visibleKeySections(data: TaskRuns, query: string): KeySection[] {
  return sectionsFromKeys(data.score_keys, data.primary)
    .map((s) => ({
      metric: s.metric,
      panels: s.panels
        .filter((p) => matchesSearch(p.title, query) || matchesSearch(p.key, query))
        .sort((a, b) => Number(b.key === data.primary) - Number(a.key === data.primary)),
    }))
    .filter((s) => s.panels.length > 0);
}

/** One bar per identity for `key`; whiskers on the primary key only. */
export function barRows(items: readonly Identity[], key: string, data: TaskRuns, colorOf: (id: string) => string): BarRow[] {
  const values = items.map((i) => scoreOf(i, key));
  const best = rowBest(values, data.higher_is_better);
  return items.map((i, n) => {
    const g = i.kind === "group" ? i.group : null;
    const t = key === data.primary ? g?.test_interval : null;
    const value = values[n] ?? null;
    return {
      id: i.id,
      name: i.name,
      color: colorOf(i.id),
      value,
      ci: t ? { lo: t.lo, hi: t.hi, method: t.method } : null,
      best: best !== null && value === best,
    };
  });
}

export interface ScoreKeySectionsProps {
  data: TaskRuns;
  items: readonly Identity[];
  colorOf: (id: string) => string;
  highlight: string | null;
  query: string;
}

export function ScoreKeySections({ data, items, colorOf, highlight, query }: ScoreKeySectionsProps): ReactElement {
  const primaryMetric = sectionsFromKeys(data.score_keys, data.primary)[0]?.metric;
  return (
    <>
      {visibleKeySections(data, query).map((s) => (
        <PanelSection
          key={s.metric}
          title={s.metric}
          count={s.panels.length}
          defaultOpen={s.metric === primaryMetric}
          storageKey={`${data.project}/${data.task}`}
          grid="small"
        >
          {s.panels.map((p) => (
            <Panel key={p.key} title={p.title} aside={p.key === data.primary ? <span className="star">★ primary</span> : undefined}>
              <Fit>{(width) => <BarPanel width={width} rows={barRows(items, p.key, data, colorOf)} metric={p.key} highlight={highlight} />}</Fit>
            </Panel>
          ))}
        </PanelSection>
      ))}
    </>
  );
}
