/**
 * Table panel: one row per source row, one column per field, sortable headers.
 */
import { type CSSProperties, useMemo, useState } from "react";
import { MINUS } from "../charts/Scale";
import type { PanelResult } from "./index";

type Row = Record<string, unknown>;
type SortDir = "asc" | "desc";

/** True minus sign, used for negative numbers (shared with the charts). */
export { MINUS };
/** Rows rendered before the table stops and shows a count. */
export const ROW_CAP = 500;

/**
 * Format a number tersely.
 *
 * Integers are grouped (`12,000`), values in [-1, 1] get three decimals (`0.663`), values
 * below 1000 get three significant digits (`12.3`), larger values are rounded and grouped.
 */
export function fmtNum(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  const a = Math.abs(v);
  let s: string;
  if (Number.isInteger(a)) s = a.toLocaleString("en-US");
  else if (a < 0.001) s = String(Number(a.toPrecision(2)));
  else if (a <= 1) s = a.toFixed(3);
  else if (a < 1000) s = String(Number(a.toPrecision(3)));
  else s = Math.round(a).toLocaleString("en-US");
  return v < 0 ? MINUS + s : s;
}

/** Render any JSON cell value as short text. Missing values become an em dash. */
export function fmtCell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return fmtNum(v);
  if (typeof v === "boolean") return v ? "✓" : "✗";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

const COLUMN_NAMES: Record<string, string> = {
  run_id: "run",
  group_id: "group",
  created_by: "by",
  "usage.usd": "$",
  "usage.seconds": "time",
};

/**
 * Header text for a field: `run_id` → `run`, `delta_prev` → `Δ prev`, `usage.tokens_in` →
 * `tokens in`, `meta.category` → `category`. The raw field stays in the header tooltip.
 */
export function columnLabel(field: string): string {
  const known = COLUMN_NAMES[field];
  if (known) return known;
  return field
    .replace(/^(usage|meta)\./, "")
    .replace(/^delta_/, "Δ ")
    .replace(/_/g, " ");
}

/** A change column (`delta_prev`, `Δ`): its numbers carry a sign. */
export function isDeltaColumn(field: string): boolean {
  return /^(delta|Δ)/i.test(field);
}

/** A signed number: `+0.025`, `−0.048`, `0`. */
export function fmtSigned(v: number): string {
  const s = fmtNum(v);
  return v > 0 && Number(s.replace(/,/g, "")) !== 0 ? `+${s}` : s;
}

/** Short run id for a cell: the last `-` segment (`…-toy-test-4093` → `4093`). */
export function shortRun(runId: string): string {
  return runId.split("-").pop() || runId;
}

/** Column names: the union of row keys, in order of first appearance. */
export function tableColumns(rows: Row[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) for (const key of Object.keys(row)) seen.add(key);
  return [...seen];
}

function isMissing(v: unknown): boolean {
  return v === null || v === undefined;
}

function compareCells(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "en", { numeric: true });
}

/** Sort rows by one column. Missing values always sort last. Returns a new array. */
export function sortRows(rows: Row[], key: string, dir: SortDir): Row[] {
  const present = rows.filter((r) => !isMissing(r[key]));
  const missing = rows.filter((r) => isMissing(r[key]));
  const sign = dir === "asc" ? 1 : -1;
  present.sort((a, b) => sign * compareCells(a[key], b[key]));
  return [...present, ...missing];
}

const S = {
  wrap: { overflowX: "auto" },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13.5,
    fontVariantNumeric: "tabular-nums",
  },
  th: {
    textAlign: "left",
    fontWeight: 500,
    color: "var(--ink-3)",
    fontSize: 12.5,
    padding: "0 12px 8px 0",
    borderBottom: "1px solid var(--rule)",
    whiteSpace: "nowrap",
  },
  sortBtn: {
    font: "inherit",
    color: "inherit",
    background: "none",
    border: 0,
    padding: 0,
    cursor: "pointer",
  },
  td: {
    padding: "7px 12px 7px 0",
    borderBottom: "1px solid var(--rule-2)",
    maxWidth: "28ch",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  foot: { fontSize: 12.5, color: "var(--ink-3)", margin: "8px 0 0" },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Table panel. Click a header to sort ascending, again for descending, again to reset. */
export function TablePanel({ result }: { result: PanelResult }) {
  const rows = result.rows as Row[];
  const cols = useMemo(() => tableColumns(rows), [rows]);
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(null);
  const sorted = useMemo(() => (sort ? sortRows(rows, sort.key, sort.dir) : rows), [rows, sort]);
  if (rows.length === 0) return <p style={S.empty}>No rows</p>;

  const numeric = new Set(cols.filter((c) => rows.some((r) => typeof r[c] === "number")));
  const toggle = (key: string) =>
    setSort((s) => {
      if (s?.key !== key) return { key, dir: "asc" };
      return s.dir === "asc" ? { key, dir: "desc" } : null;
    });
  const ariaSort = (key: string) =>
    sort?.key === key ? (sort.dir === "asc" ? "ascending" : "descending") : "none";

  return (
    <div style={S.wrap}>
      <table style={S.table}>
        <thead>
          <tr>
            {cols.map((c) => (
              <th
                key={c}
                aria-sort={ariaSort(c)}
                style={{ ...S.th, textAlign: numeric.has(c) ? "right" : "left" }}
              >
                <button type="button" style={S.sortBtn} title={c} onClick={() => toggle(c)}>
                  {columnLabel(c)}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, ROW_CAP).map((row, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = row[c];
                const text = typeof v === "number" && isDeltaColumn(c) ? fmtSigned(v) : fmtCell(v);
                const align = typeof v === "number" || (numeric.has(c) && (v === null || v === undefined)) ? "right" : "left";
                return (
                  <td key={c} title={text} style={{ ...S.td, textAlign: align }}>
                    {c === "run_id" && typeof v === "string" ? (
                      <a href={`/r/${encodeURIComponent(v)}`}>{shortRun(v)}</a>
                    ) : (
                      text
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > ROW_CAP && (
        <p style={S.foot}>
          {fmtNum(ROW_CAP)} of {fmtNum(rows.length)} rows
        </p>
      )}
    </div>
  );
}

export default TablePanel;
