/**
 * `stat_strip` panel: a row of big numbers with short labels.
 *
 * Rows are `{label, value, unit, tooltip}`; the tooltip is the only place for
 * explanation.
 */
import type { ReactElement } from "react";
import { fmtValue } from "../charts/Scale";
import type { PanelProps } from "./index";

/** One stat, as sent by the server. */
export interface StatRow {
  label: string;
  value: string | number | null;
  unit?: string | null;
  tooltip?: string | null;
}

/** Format a stat value: numbers via `fmtValue`, strings as sent, missing as a dash. */
export function fmtStat(value: unknown): string {
  if (typeof value === "number") return fmtValue(value);
  if (typeof value === "string" && value !== "") return value;
  return "—";
}

function asStat(row: Record<string, unknown>): StatRow | null {
  if (typeof row.label !== "string") return null;
  return {
    label: row.label,
    value: typeof row.value === "number" || typeof row.value === "string" ? row.value : null,
    unit: typeof row.unit === "string" ? row.unit : null,
    tooltip: typeof row.tooltip === "string" ? row.tooltip : null,
  };
}

/** Draw a `stat_strip` panel result. */
export function StatStrip({ result }: PanelProps): ReactElement {
  const rows = result.rows.map(asStat).filter((r): r is StatRow => r !== null);
  if (rows.length === 0) return <p className="panel-empty">No stats yet</p>;
  return (
    <dl className="stats">
      {rows.map((r, i) => (
        <div key={`${r.label}-${i}`} title={r.tooltip ?? undefined}>
          <dt>{r.label}</dt>
          <dd>
            {fmtStat(r.value)}
            {r.unit ? <small> {r.unit}</small> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
