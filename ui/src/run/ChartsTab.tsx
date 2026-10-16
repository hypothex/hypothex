/** Run Charts tab (spec 4.3): every step metric, sectioned by prefix, this run in colour and its seeds grey. */
import { PanelSection } from "../chrome/PanelSection";
import { metricSections, stepMetrics } from "./curves";
import { MetricPanels, useRunCurves } from "./MetricPanels";
import type { RunContext } from "./runContext";

export function ChartsTab({ ctx }: { ctx: RunContext }) {
  const names = stepMetrics(ctx.detail.metric_names);
  const curves = useRunCurves(ctx, names);
  if (names.length === 0) {
    return (
      <div className="rmain">
        <p className="muted">No step metrics logged</p>
      </div>
    );
  }
  return (
    <div className="rmain">
      <p className="muted">
        {ctx.identity.siblings.length > 0 ? "This run in colour, the other seeds of its config in grey." : "This run's step metrics."}
      </p>
      {metricSections(names).map((section) => (
        <PanelSection key={section.title} title={section.title} count={section.metrics.length} grid="wide">
          <MetricPanels ctx={ctx} metrics={section.metrics} height={180} curves={curves} />
        </PanelSection>
      ))}
    </div>
  );
}
