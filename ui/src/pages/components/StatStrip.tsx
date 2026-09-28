/** A row of big numbers with short labels; explanations go in the tooltip. Drawn by the `stat_strip` panel. */
import type { StatItem } from "../../api/models";
import { StatStrip as StatStripPanel } from "../../panels/StatStrip";

export type { StatItem };

export function StatStrip({ items }: { items: StatItem[] }) {
  if (items.length === 0) return null;
  const rows: Record<string, unknown>[] = items.map((item) => ({
    label: item.label,
    value: item.value,
    unit: item.unit ?? null,
    tooltip: item.tooltip ?? null,
  }));
  return <StatStripPanel result={{ type: "stat_strip", title: "", rows, meta: {} }} />;
}
