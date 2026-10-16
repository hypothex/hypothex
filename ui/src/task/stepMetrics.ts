/**
 * Step metrics (spec 4.2, 4.3): which logged metrics are drawn over time, and their
 * sections by the first `/` prefix. The Task and Run Charts tabs share these helpers so
 * both show the same metric set.
 */
import { SWEEP_PREFIX } from "../pages/components/KindPanels";

export interface MetricSection {
  title: string;
  metrics: string[];
}

/** Metrics over time: `sweep/*` (step = the swept value) and the step counter are left out. */
export function stepMetrics(names: readonly string[]): string[] {
  return names.filter((n) => !n.startsWith(SWEEP_PREFIX) && n !== "step");
}

/** One section per first `/` prefix, first-seen order; names without a prefix go to "metrics". */
export function metricSections(names: readonly string[]): MetricSection[] {
  const out = new Map<string, string[]>();
  for (const name of names) {
    const cut = name.indexOf("/");
    const title = cut > 0 ? name.slice(0, cut) : "metrics";
    out.set(title, [...(out.get(title) ?? []), name]);
  }
  return [...out].map(([title, metrics]) => ({ title, metrics }));
}
