/**
 * Examples tab: the existing Examples screen for two visible configs (latest finished run
 * of each), A = runner-up, B = best in list order by default; two selects change them.
 */
import { type ReactElement, useState } from "react";
import type { Leaderboard, TaskRuns } from "../api/models";
import { EmptyState } from "../chrome/EmptyState";
import { ExamplesPage } from "../pages/Examples";
import { primaryMetricName } from "../pages/components/format";
import { type Selection, latestRun, listIdentities } from "./useRunSelection";

export function examplesCandidates(selection: Selection, data: TaskRuns): { id: string; name: string; runId: string }[] {
  return listIdentities(selection, data)
    .filter((i) => !i.hidden)
    .flatMap((i) => {
      const run = latestRun(i.runs.filter((r) => r.status === "finished"));
      return run ? [{ id: i.id, name: i.name, runId: run.run_id }] : [];
    });
}

export interface ExamplesTabProps {
  data: TaskRuns;
  board: Leaderboard | undefined;
  selection: Selection;
}

export function ExamplesTab({ data, board, selection }: ExamplesTabProps): ReactElement {
  const items = examplesCandidates(selection, data);
  const [a, setA] = useState<string | null>(null);
  const [b, setB] = useState<string | null>(null);
  const runA = a ?? items[1]?.runId ?? null;
  const runB = b ?? items[0]?.runId ?? null;
  if (items.length < 2 || runA === null || runB === null) return <EmptyState title="Needs two finished runs" />;
  const metric = primaryMetricName(data.primary);
  const version = board?.metric_versions[metric];
  const pick = (label: string, value: string, set: (v: string) => void): ReactElement => (
    <label>
      {label}
      <select className="ctl" aria-label={`Run ${label}`} value={value} onChange={(e) => set(e.target.value)}>
        {items.map((i) => (
          <option key={i.id} value={i.runId}>
            {i.name}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <div className="examples-tab panels">
      <div className="ptools">
        {pick("A", runA, setA)}
        {pick("B", runB, setB)}
      </div>
      <ExamplesPage key={`${runA}/${runB}`} a={runA} b={runB} metric={version ? `${metric}@${version}` : metric} />
    </div>
  );
}
