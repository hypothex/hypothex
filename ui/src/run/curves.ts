/** Which step metrics the run page draws, and as which series (spec 4.3 Curves, Charts tab). */
import type { MetricPoint } from "../api/models";
import type { LineSeries } from "../charts/LineChart";

export { metricSections, stepMetrics } from "../task/stepMetrics";

/** The Overview's curves: the primary's metric (`val/top1` for `top1/value`), then losses, then the rest. */
export function pickCurves(names: readonly string[], primary: string | null, n = 3): string[] {
  const metric = primary?.split("/")[0] ?? "";
  const first = metric ? names.filter((x) => x === metric || x.endsWith(`/${metric}`)) : [];
  const losses = names.filter((x) => /loss/i.test(x));
  return [...new Set([...first, ...losses, ...names])].slice(0, n);
}

/** This run in its identity colour (drawn last, on top); sibling seeds grey and faint. */
export function curveSeries(
  byRun: ReadonlyMap<string, readonly MetricPoint[]>,
  metric: string,
  runId: string,
  color: string,
  labels: ReadonlyMap<string, string>,
): LineSeries[] {
  const out: LineSeries[] = [];
  for (const [id, points] of byRun) {
    const pts = points.filter((p) => p.name === metric).map((p): [number, number] => [p.step, p.value]);
    if (pts.length === 0) continue;
    const me = id === runId;
    out.push({ id, name: labels.get(id) ?? id, color: me ? color : "var(--c0)", points: pts, bold: me, faint: !me });
  }
  return out.sort((a, b) => Number(a.id === runId) - Number(b.id === runId));
}
