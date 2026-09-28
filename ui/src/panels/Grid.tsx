/**
 * Grid panel: items x groups outcome matrix. Each cell is the fraction of seeds that solved
 * the item; darker is more. Columns run hardest (left) to easiest (right).
 */
import type { CSSProperties } from "react";
import type { GridRow } from "../api/models";
import { FS, useElementWidth } from "../charts/Scale";
import type { PanelResult } from "./index";
import { fmtNum } from "./Table";

/** One grid cell (contract 1.6). */
export type { GridRow };
/** A group with its display label. */
export type GridGroup = { group_id: string; label: string };
/** Everything needed to draw the grid. */
export type GridLayout = { items: string[]; groups: GridGroup[]; cells: Map<string, number> };

/** Map key of one cell. */
export const cellKey = (groupId: string, itemId: string): string => `${groupId}\u0000${itemId}`;

/** Cell colour: paper for 0, ink for 1, ink mixed into paper in between (1/3 -> 29%). */
export function cellFill(v: number): string {
  if (v <= 0) return "var(--paper-2)";
  if (v >= 1) return "var(--ink)";
  return `color-mix(in srgb, var(--ink) ${Math.round(v * 87)}%, var(--paper))`;
}

function byDifficulty(rows: GridRow[]): string[] {
  const acc = new Map<string, { sum: number; n: number }>();
  for (const r of rows) {
    const a = acc.get(r.item_id) ?? { sum: 0, n: 0 };
    a.sum += r.value;
    a.n += 1;
    acc.set(r.item_id, a);
  }
  const mean = (id: string) => {
    const a = acc.get(id);
    return a ? a.sum / a.n : 0;
  };
  return [...acc.keys()].sort(
    (a, b) => mean(a) - mean(b) || a.localeCompare(b, "en", { numeric: true }),
  );
}

/**
 * Resolve item order, group order and cell values.
 *
 * `meta.items` and `meta.groups` win when present; items or groups seen only in rows are
 * appended (items by difficulty, groups labelled by id).
 */
export function gridLayout(rows: GridRow[], meta: Record<string, unknown>): GridLayout {
  const metaItems = Array.isArray(meta.items)
    ? meta.items.filter((v): v is string => typeof v === "string")
    : [];
  const items = [...metaItems];
  const seenItems = new Set(items);
  for (const id of byDifficulty(rows)) if (!seenItems.has(id)) items.push(id);

  const groups: GridGroup[] = [];
  const seenGroups = new Set<string>();
  if (Array.isArray(meta.groups)) {
    for (const g of meta.groups as Partial<GridGroup>[]) {
      if (typeof g?.group_id === "string" && !seenGroups.has(g.group_id)) {
        groups.push({
          group_id: g.group_id,
          label: typeof g.label === "string" ? g.label : g.group_id,
        });
        seenGroups.add(g.group_id);
      }
    }
  }
  for (const r of rows) {
    if (!seenGroups.has(r.group_id)) {
      groups.push({ group_id: r.group_id, label: r.group_id });
      seenGroups.add(r.group_id);
    }
  }
  const cells = new Map<string, number>();
  for (const r of rows) cells.set(cellKey(r.group_id, r.item_id), r.value);
  return { items, groups, cells };
}

/** Width used before layout is known (and in test DOMs). */
export const GRID_FALLBACK_W = 720;
/** Least width of the label gutter (group label plus the solved count). */
export const MIN_LW = 150;

/** Gutter width for these labels: room for the longest label at 12 px plus the count. */
export function labelGutter(groups: GridGroup[]): number {
  const longest = Math.max(0, ...groups.map((g) => g.label.length));
  return Math.min(260, Math.max(MIN_LW, Math.ceil(longest * 7 + 56)));
}
const TOP = 24;
const RH = 24;
const CH = 18;

const T = {
  tk: { fontSize: FS.tick, fill: "var(--ink-3)", fontVariantNumeric: "tabular-nums" },
  lbl: { fontSize: FS.label, fill: "var(--ink-2)" },
  lblS: { fontSize: FS.tick, fill: "var(--ink-3)" },
  key: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px 20px",
    marginTop: 14,
    fontSize: 13,
    color: "var(--ink-2)",
    alignItems: "center",
  },
  keyItem: { display: "inline-flex", alignItems: "center", gap: 7 },
  sw: { width: 10, height: 10, borderRadius: 2, display: "inline-block" },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Grid panel. Reads `meta.items` (hardest first) and `meta.groups`. */
export function GridPanel({ result }: { result: PanelResult }) {
  const [ref, W] = useElementWidth<HTMLDivElement>(GRID_FALLBACK_W);
  const rows = result.rows as unknown as GridRow[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  if (rows.length === 0) return <p style={T.empty}>No items</p>;
  const { items, groups, cells } = gridLayout(rows, meta);
  const LW = labelGutter(groups);
  const cw = (W - LW) / items.length;
  const gap = cw > 4 ? 1 : 0;
  const yb = TOP + groups.length * RH + 14;

  return (
    <div ref={ref}>
      <svg
        width={W}
        height={yb + 6}
        role="img"
        aria-label={`Share of seeds solved for ${items.length} items by ${groups.length} groups`}
        style={{ display: "block", overflow: "visible", fontFamily: "var(--sans)" }}
      >
        <text x={LW - 12} y={TOP - 10} textAnchor="end" style={T.lblS}>
          solved
        </text>
        {groups.map((g, r) => {
          const y = TOP + r * RH;
          const solved = items.reduce(
            (acc, id) => acc + (cells.get(cellKey(g.group_id, id)) ?? 0),
            0,
          );
          return (
            <g key={g.group_id} data-group={g.group_id}>
              <text x={0} y={y + CH / 2 + 4} style={T.lbl}>
                {g.label}
              </text>
              <text
                data-solved={Math.round(solved)}
                x={LW - 12}
                y={y + CH / 2 + 4}
                textAnchor="end"
                style={T.tk}
              >
                <title>{`${fmtNum(solved)} items solved on average over seeds`}</title>
                {Math.round(solved)}
              </text>
              {items.map((id, j) => {
                const v = cells.get(cellKey(g.group_id, id));
                if (v === undefined) return null;
                return (
                  <rect
                    key={id}
                    data-item={id}
                    x={LW + j * cw}
                    y={y}
                    width={Math.max(1, cw - gap)}
                    height={CH}
                    style={{ fill: cellFill(v) }}
                  >
                    <title>{`${id}\n${g.label}: ${fmtNum(v)} of seeds solved`}</title>
                  </rect>
                );
              })}
            </g>
          );
        })}
        <text x={LW} y={yb} style={T.lblS}>
          hard
        </text>
        <text x={W} y={yb} textAnchor="end" style={T.lblS}>
          easy
        </text>
      </svg>
      <div style={T.key} aria-label="Key">
        {[0, 0.5, 1].map((v) => (
          <span key={v} style={T.keyItem}>
            <i
              style={{
                ...T.sw,
                background: cellFill(v),
                ...(v === 0 ? { outline: "1px solid var(--rule)", outlineOffset: -1 } : {}),
              }}
            />
            {v}
          </span>
        ))}
        <span style={{ color: "var(--ink-3)" }}>share of seeds solved</span>
      </div>
    </div>
  );
}

export default GridPanel;
