/**
 * Kind-specific run detail (spec 8.4): the task kind's `run_view` panels from
 * `GET /tasks/{p}/{t}/kind`, scoped to one run, plus a trace section for agent kinds.
 */
import { useMemo } from "react";

import { useRunTrace, useRunTraces, useViewQuery } from "../../api/queries";
import { Figure, panelLetter } from "./Figure";
import { AppLink, hrefs } from "./links";
import { PanelBody, PanelGrid } from "./PanelGrid";
import { ErrorBox, Loading } from "./QueryState";
import type { PanelResult, PanelSpec, TraceSummary } from "./types";

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

/** Metrics a sweep logs with step = its swept value (e.g. concurrency), not time. */
export const SWEEP_PREFIX = "sweep/";

/**
 * A run's curves are over time; a `sweep/*` metric is over its swept value, so a curves
 * panel with no metric list (the system_bench "over time" panel) leaves it out. The task
 * page plots sweeps. A panel that lists metrics keeps what it lists; other types are
 * returned unchanged.
 */
export function withoutSweeps(result: PanelResult, spec: PanelSpec | undefined): PanelResult {
  if (result.type !== "curves" || (spec?.data?.metrics?.length ?? 0) > 0) return result;
  const isSweep = (name: unknown): boolean => typeof name === "string" && name.startsWith(SWEEP_PREFIX);
  if (!result.rows.some((row) => isSweep(row.name))) return result;
  const metrics = result.meta.metrics;
  return {
    ...result,
    rows: result.rows.filter((row) => !isSweep(row.name)),
    meta: Array.isArray(metrics) ? { ...result.meta, metrics: metrics.filter((m) => !isSweep(m)) } : result.meta,
  };
}

/** Trace panels are drawn by the trace section; everything else goes through the query. */
export function splitRunView(specs: PanelSpec[]): { regular: PanelSpec[]; trace: PanelSpec | null } {
  return {
    regular: specs.filter((p) => p.type !== "trace"),
    trace: specs.find((p) => p.type === "trace") ?? null,
  };
}

/** A panel that shows traces: the trace section, or a panel reading `source: traces`. */
export function readsTraces(panel: PanelSpec): boolean {
  return panel.type === "trace" || (panel.data as { source?: unknown } | undefined)?.source === "traces";
}

/** `tokens per turn` → `Tokens per turn`. */
export function sentenceCase(title: string): string {
  return title ? title.charAt(0).toUpperCase() + title.slice(1) : title;
}

/**
 * The run-view panels to draw for one run: titles in sentence case (as the page's own
 * sections), and, when the run has no traces (`traceCount === 0`), no trace panels, which
 * would only say "no traces". `traceCount` undefined (not known yet) keeps them.
 * Curves explicitly name the series the page draws, with the server's per-series cap.
 * A long terminal history is split at the API's 100-reference limit, never truncated.
 */
export function runViewPanels(
  specs: PanelSpec[],
  traceCount?: number,
  metricNames: readonly string[] = [],
): PanelSpec[] {
  const kept = traceCount === 0 ? specs.filter((p) => !readsTraces(p)) : specs;
  return kept.flatMap((original): PanelSpec[] => {
    const panel = original.title ? { ...original, title: sentenceCase(original.title) } : original;
    if (panel.type !== "curves") return [panel];
    const data = panel.data ?? {};
    const names = data.metrics ?? metricNames.filter(
      (name) => !name.startsWith(SWEEP_PREFIX) && name !== (data.step_metric ?? "step"),
    );
    const chunks: string[][] = [];
    for (let i = 0; i < names.length; i += 100) chunks.push(names.slice(i, i + 100));
    // [] means no displayed history: omitting the list would read every hidden series.
    if (chunks.length === 0) chunks.push([]);
    return chunks.map((metrics, i) => ({
      ...panel,
      ...(chunks.length > 1 ? { title: `${panel.title || "Metrics"} · ${i * 100 + 1}–${i * 100 + metrics.length}` } : {}),
      data: { ...data, metrics, max_points: data.max_points ?? 500 },
    }));
  });
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
  // `specs` is memoized by the caller, so `regular` and `results` keep their identity across renders
  const { regular, trace } = useMemo(() => splitRunView(specs), [specs]);
  const panels = useViewQuery(
    project,
    task,
    regular.length > 0 ? { view: { title: "run", panels: regular.map((p) => scopeToRun(p, runId)) } } : null,
  );
  const results = useMemo(
    () => panels.data?.panels.map((result, i) => withoutSweeps(result, regular[i])),
    [panels.data, regular],
  );
  if (specs.length === 0) return null;
  return (
    <>
      {panels.error ? <ErrorBox error={panels.error} /> : null}
      {regular.length > 0 && results ? (
        <PanelGrid results={results} specs={regular} startIndex={startIndex} />
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
