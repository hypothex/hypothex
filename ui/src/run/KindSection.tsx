/**
 * The task kind's run panels (spec 8.4) in v5 panel chrome: every panel scoped to this run
 * (the cross-config grid stays unscoped), and a trace panel for agent kinds with a picker,
 * the failed trace first unless `?example=` names one. Curves are left to the Charts tab.
 */
import { useMemo } from "react";
import type { PanelSpec, RunStatus, TaskKindInfo, TraceSummary } from "../api/models";
import { useRunTrace, useRunTraces, useViewQuery } from "../api/queries";
import { Panel } from "../chrome/Panel";
import { pickExample, runViewPanels, scopeToRun, splitRunView, withoutSweeps } from "../pages/components/KindPanels";
import { AppLink, hrefs } from "../pages/components/links";
import { PanelBody } from "../pages/components/PanelGrid";
import { ErrorBox, Loading } from "../pages/components/QueryState";

/** The run view panels to draw on the Overview: sentence-case titles, no curves, no empty trace panels. */
export function runPanelSpecs(kind: TaskKindInfo | null, traceCount: number | undefined, metricNames: readonly string[]): PanelSpec[] {
  return runViewPanels(kind?.run_view ?? [], traceCount, metricNames).filter((p) => p.type !== "curves");
}

interface TracePanelProps {
  runId: string;
  title: string;
  chosen: string | null;
  list: TraceSummary[] | undefined;
  listError: unknown;
}

function TracePanel({ runId, title, chosen, list, listError }: TracePanelProps) {
  const trace = useRunTrace(runId, chosen);
  const traces = list ?? [];
  return (
    <Panel title={chosen ? `${title} · ${chosen}` : title} aside={list ? `${traces.length} traced` : undefined}>
      {listError ? <ErrorBox error={listError} /> : null}
      {traces.length > 0 ? (
        <nav className="trace-pick" aria-label="Traced examples">
          {traces.map((t) => (
            <AppLink
              key={t.example_id}
              href={hrefs.run(runId, { example: t.example_id })}
              aria-current={t.example_id === chosen ? "true" : undefined}
              className={t.failed ? "failed" : undefined}
              title={`${t.turns} turns${t.failed ? ", failed" : ""}`}
            >
              {t.example_id}
            </AppLink>
          ))}
        </nav>
      ) : list ? (
        <p className="muted">no traces</p>
      ) : null}
      {trace.error ? <ErrorBox error={trace.error} /> : trace.data ? <PanelBody result={trace.data} /> : chosen ? <Loading /> : null}
    </Panel>
  );
}

export interface KindSectionProps {
  project: string;
  task: string;
  runId: string;
  specs: PanelSpec[];
  example?: string;
  currentGroupId?: string;
  runStatus?: RunStatus;
}

export function KindSection({ project, task, runId, specs, example, currentGroupId, runStatus }: KindSectionProps) {
  const { regular, trace } = useMemo(() => splitRunView(specs), [specs]);
  const traces = useRunTraces(runId, trace !== null);
  const chosen = example ? String(example) : pickExample(traces.data ?? []);
  const traceFirst = specs[0]?.type === "trace";
  // a current-target grid must never briefly render every target while the selection loads
  const waitingForTarget = trace !== null && regular.some((p) => p.type === "grid") && chosen === null;
  const panels = useViewQuery(
    project,
    task,
    regular.length > 0 ? { view: { title: "run", panels: regular.map((p) => scopeToRun(p, runId)) } } : null,
  );
  const results = useMemo(() => panels.data?.panels.map((r, i) => withoutSweeps(r, regular[i])), [panels.data, regular]);
  if (specs.length === 0) return null;
  const trajectory = trace ? (
    <TracePanel runId={runId} title={trace.title || "Trajectory"} chosen={chosen} list={traces.data} listError={traces.error} />
  ) : null;
  return (
    <section aria-label="Panels" className="kind-panels">
      {traceFirst ? trajectory : null}
      {panels.error ? <ErrorBox error={panels.error} /> : null}
      {regular.length > 0 && results && !waitingForTarget ? (
        results.map((result, i) => (
          <Panel key={`${i}-${result.type}`} title={result.title || regular[i]?.title || result.type}>
            <PanelBody result={result} selectedItemId={chosen ?? undefined} currentGroupId={currentGroupId} runStatus={runStatus} />
          </Panel>
        ))
      ) : waitingForTarget && traces.data ? (
        <p className="muted">No traced example available for comparison</p>
      ) : regular.length > 0 && !panels.error && !traces.error ? (
        <Loading />
      ) : null}
      {traceFirst ? null : trajectory}
    </section>
  );
}
