/**
 * Step metrics (spec 4.2): one line panel per logged metric, a section per first `/`
 * prefix, crosshair synced inside a section (`crosshairGroup`). The histories come from
 * one `views/query` of curves panels over the visible runs only.
 */
import type { ReactElement } from "react";
import { useViewQuery } from "../api/queries";
import { Fit } from "../charts/Fit";
import { LineChart } from "../charts/LineChart";
import { Panel } from "../chrome/Panel";
import { PanelSection } from "../chrome/PanelSection";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import {
  type CurvePoint,
  type MetricSection,
  type SeedsMode,
  type XMode,
  X_AXIS,
  X_LABEL,
  curveSeries,
  matchesSearch,
  stepCurvesBody,
} from "./stepMetrics";
import type { Identity } from "./useRunSelection";

export interface StepCurves {
  points: CurvePoint[];
  error: Error | null;
  loading: boolean;
}

/** The histories of `metricNames` for the runs of `items` (idle with no metrics or no runs). */
export function useStepCurves(project: string, task: string, metricNames: readonly string[], items: readonly Identity[]): StepCurves {
  const runIds = items.flatMap((i) => i.runs.map((r) => r.run_id));
  const body = stepCurvesBody(metricNames, runIds);
  const query = useViewQuery(project, task, body);
  const failed = query.data?.panels.map((p) => p.meta.error).find((e): e is string => typeof e === "string");
  return {
    points: (query.data?.panels ?? []).flatMap((p) => p.rows as unknown as CurvePoint[]),
    error: query.error ?? (failed ? new Error(failed) : null),
    loading: body !== null && (query.isPending || query.isPlaceholderData),
  };
}

export interface StepMetricsSectionProps {
  curves: StepCurves;
  sections: readonly MetricSection[];
  items: readonly Identity[];
  colorOf: (id: string) => string;
  highlight: string | null;
  query: string;
  smoothing: number;
  x: XMode;
  seeds: SeedsMode;
  /** `${project}/${task}`: section open state per task. */
  storageKey: string;
  onAddPanel?: () => void;
}

export function StepMetricsSection(props: StepMetricsSectionProps): ReactElement {
  const { curves, sections, items, colorOf, highlight, query, smoothing, x, seeds, storageKey, onAddPanel } = props;
  return (
    <>
      {sections.map((s) => {
        const metrics = s.metrics.filter((m) => matchesSearch(m, query));
        if (metrics.length === 0) return null;
        return (
          <PanelSection key={s.title} title={s.title} count={metrics.length} storageKey={storageKey} onAddPanel={onAddPanel}>
            {curves.error ? <ErrorBox error={curves.error} /> : null}
            {metrics.map((m) => (
              <Panel key={m} title={m}>
                {curves.loading ? (
                  <Loading />
                ) : (
                  <Fit>
                    {(width) => (
                      <LineChart
                        width={width}
                        series={curveSeries(curves.points, m, items, colorOf, seeds, x)}
                        smoothing={smoothing}
                        crosshairGroup={`step:${s.title}`}
                        xAxis={X_AXIS[x]}
                        xLabel={X_LABEL[x]}
                        highlight={highlight}
                      />
                    )}
                  </Fit>
                )}
              </Panel>
            ))}
          </PanelSection>
        );
      })}
    </>
  );
}
