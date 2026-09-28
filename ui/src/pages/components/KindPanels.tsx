/**
 * Kind-specific run detail (spec 8.4): the task kind's `run_view` panels from
 * `GET /tasks/{p}/{t}/kind`, scoped to one run, plus a trace section for agent kinds.
 */
import { useRunTrace, useRunTraces, useViewQuery } from "../../api/queries";
import { Figure, panelLetter } from "./Figure";
import { AppLink, hrefs } from "./links";
import { PanelBody, PanelGrid } from "./PanelGrid";
import { ErrorBox, Loading } from "./QueryState";
import type { PanelSpec, TraceSummary } from "./types";

/**
 * Panel types that compare runs, so they stay unscoped on the run page: the agent kinds'
 * `grid "same item across configs"` (spec 8.4) shows this run's items next to the other
 * configs of the task.
 */
export const CROSS_RUN_TYPES: ReadonlySet<string> = new Set(["grid"]);

/**
 * Restrict a panel to one run: every source row carries `run_id` (contract 1.5).
 * Panels in `CROSS_RUN_TYPES` come back unchanged.
 */
export function scopeToRun(panel: PanelSpec, runId: string): PanelSpec {
  if (CROSS_RUN_TYPES.has(panel.type)) return panel;
  const data = { ...(panel.data ?? {}) };
  const filter = { ...((data.filter as Record<string, unknown> | undefined) ?? {}), run_id: runId };
  return { ...panel, data: { ...data, filter } };
}

/** Trace panels are drawn by the trace section; everything else goes through the query. */
export function splitRunView(specs: PanelSpec[]): { regular: PanelSpec[]; trace: PanelSpec | null } {
  return {
    regular: specs.filter((p) => p.type !== "trace"),
    trace: specs.find((p) => p.type === "trace") ?? null,
  };
}

/** How many lettered panels `KindPanels` draws for these specs. */
export function kindPanelCount(specs: PanelSpec[]): number {
  const { regular, trace } = splitRunView(specs);
  return regular.length + (trace ? 1 : 0);
}

/** The example to show first: the first failed trace, else the first trace. */
export function pickExample(traces: TraceSummary[]): string | null {
  return (traces.find((t) => t.failed) ?? traces[0])?.example_id ?? null;
}

export interface TraceSectionProps {
  runId: string;
  example?: string;
  letter: string;
  title: string;
}

export function TraceSection({ runId, example, letter, title }: TraceSectionProps) {
  const list = useRunTraces(runId);
  const traces = list.data ?? [];
  const chosen = example ? String(example) : pickExample(traces);
  const trace = useRunTrace(runId, chosen);
  return (
    <Figure
      letter={letter}
      title={chosen ? `${title} · ${chosen}` : title}
      aside={list.data ? `${traces.length} traced` : undefined}
    >
      {list.error ? <ErrorBox error={list.error} /> : null}
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
      ) : list.data ? (
        <p className="small">no traces</p>
      ) : null}
      {trace.error ? (
        <ErrorBox error={trace.error} />
      ) : trace.data ? (
        <PanelBody result={trace.data} />
      ) : chosen ? (
        <Loading />
      ) : null}
    </Figure>
  );
}

export interface KindPanelsProps {
  project: string;
  task: string;
  runId: string;
  specs: PanelSpec[];
  example?: string;
  startIndex: number;
}

export function KindPanels({ project, task, runId, specs, example, startIndex }: KindPanelsProps) {
  const { regular, trace } = splitRunView(specs);
  const panels = useViewQuery(
    project,
    task,
    regular.length > 0 ? { view: { title: "run", panels: regular.map((p) => scopeToRun(p, runId)) } } : null,
  );
  if (specs.length === 0) return null;
  return (
    <>
      {panels.error ? <ErrorBox error={panels.error} /> : null}
      {regular.length > 0 && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={regular} startIndex={startIndex} />
      ) : regular.length > 0 && !panels.error ? (
        <Loading />
      ) : null}
      {trace ? (
        <TraceSection
          runId={runId}
          example={example}
          letter={panelLetter(startIndex + regular.length)}
          title={trace.title || "Trajectory"}
        />
      ) : null}
    </>
  );
}
