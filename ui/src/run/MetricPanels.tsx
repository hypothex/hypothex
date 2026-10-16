/** Step-metric panels of one run: this run in colour, up to four sibling seeds grey, one crosshair. */
import type { MetricPoint } from "../api/models";
import { useRunsMetrics } from "../api/queries";
import { Fit } from "../charts/Fit";
import { LineChart } from "../charts/LineChart";
import { Panel } from "../chrome/Panel";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { curveSeries } from "./curves";
import type { RunContext } from "./runContext";

export const MAX_SIBLINGS = 4;
export const CURVE_POINTS = 300;

export function useRunCurves(ctx: RunContext, metrics: readonly string[]) {
  const ids = [ctx.runId, ...ctx.identity.siblings.slice(0, MAX_SIBLINGS).map((r) => r.run_id)];
  return useRunsMetrics(ids, metrics, CURVE_POINTS);
}

export interface MetricPanelsProps {
  ctx: RunContext;
  metrics: readonly string[];
  height: number;
  curves: { byRun: Map<string, MetricPoint[]>; error: Error | null; pending: boolean };
}

export function MetricPanels({ ctx, metrics, height, curves }: MetricPanelsProps) {
  const labels = new Map<string, string>([
    [ctx.runId, "this run"],
    ...ctx.identity.siblings.map((r): [string, string] => [r.run_id, r.seed === null ? r.run_id : `seed ${r.seed}`]),
  ]);
  return (
    <>
      {curves.error ? <ErrorBox error={curves.error} /> : null}
      <div className="curves">
        {metrics.map((metric) => (
          <Panel key={metric} title={metric}>
            {curves.pending ? (
              <Loading />
            ) : (
              <Fit minHeight={height}>
                {(width) => (
                  <LineChart
                    width={width}
                    height={height}
                    series={curveSeries(curves.byRun, metric, ctx.runId, ctx.identity.color, labels)}
                    crosshairGroup={`run:${ctx.runId}`}
                  />
                )}
              </Fit>
            )}
          </Panel>
        ))}
      </div>
    </>
  );
}
