import type { ReactNode } from "react";
import type { PanelResult } from "../api/models";
import { panelLetter } from "../pages/components/Figure";
import { clampSpan } from "../pages/components/PanelGrid";

/** One computed panel from `POST views/query` (contract 1.6), and the journal-style letter. */
export type { PanelResult };
export { panelLetter };

/** A panel's `layout:` block; missing values take the contract defaults. */
export interface LayoutHint {
  span?: number;
  row?: number | null;
}

/** Where a panel lands on the 12-column grid. `col` and `row` are 1-based. */
export interface Placement {
  col: number;
  span: number;
  row: number;
  /** True when an explicit row has no room left; the panel is drawn over its neighbours. */
  overflow: boolean;
}

const COLUMNS = 12;

/**
 * Place panels on the 12-column grid the way CSS grid's sparse auto-placement does.
 *
 * Panels with a `row` go first, left to right in that row. Panels without one then
 * flow from row 1 column 1, never moving back. The preview draws panels at these
 * exact cells, so the ruler and the preview always agree.
 */
export function placePanels(layouts: LayoutHint[]): Placement[] {
  const used = new Map<number, boolean[]>();
  const cells = (row: number): boolean[] => {
    let r = used.get(row);
    if (!r) {
      r = new Array<boolean>(COLUMNS).fill(false);
      used.set(row, r);
    }
    return r;
  };
  const fits = (row: number, col: number, span: number) =>
    col + span <= COLUMNS && cells(row).slice(col, col + span).every((c) => !c);
  const take = (row: number, col: number, span: number) => {
    const r = cells(row);
    for (let c = col; c < col + span; c++) r[c] = true;
  };
  const out = new Array<Placement>(layouts.length);
  const rowCursor = new Map<number, number>();
  layouts.forEach((l, i) => {
    if (l.row == null) return;
    const span = clampSpan(l.span);
    const row = Math.max(1, Math.floor(l.row));
    let col = rowCursor.get(row) ?? 0;
    while (col + span <= COLUMNS && !fits(row, col, span)) col++;
    const overflow = col + span > COLUMNS;
    if (overflow) col = COLUMNS - span;
    else take(row, col, span);
    rowCursor.set(row, col + span);
    out[i] = { col: col + 1, span, row, overflow };
  });
  let row = 1;
  let col = 0;
  layouts.forEach((l, i) => {
    if (l.row != null) return;
    const span = clampSpan(l.span);
    while (!fits(row, col, span)) {
      col++;
      if (col + span > COLUMNS) {
        row++;
        col = 0;
      }
    }
    take(row, col, span);
    out[i] = { col: col + 1, span, row, overflow: false };
    col += span;
  });
  return out;
}

export interface LayoutRulerProps {
  placement: Placement | null;
  label: string;
}

/** Twelve column ticks; the selected panel's columns are lit. */
export function LayoutRuler({ placement, label }: LayoutRulerProps) {
  const on = (c: number) => placement !== null && c >= placement.col && c < placement.col + placement.span;
  return (
    <div className="hx-ed-ruler-wrap">
      <div className="hx-ed-pv-h">
        <span className="t">Preview</span>
        <span className="aside" data-testid="ruler-label">
          {label}
        </span>
      </div>
      <div className="hx-ed-ruler" aria-hidden="true">
        {Array.from({ length: COLUMNS }, (_, i) => i + 1).map((c) => (
          <span key={c} className={on(c) ? "on" : undefined}>
            <b>{c}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export interface PreviewProps {
  results: PanelResult[];
  layouts: LayoutHint[];
  selected: number | null;
  /** Result index -> validation message shown in place of that panel. */
  problems: Record<number, string>;
  /** True while the YAML is invalid and the preview shows the last valid view. */
  stale: boolean;
  renderPanel: (result: PanelResult) => ReactNode;
  onSelect?: (index: number) => void;
}

/** Live preview of the unsaved view on the 12-column grid. */
export function Preview({ results, layouts, selected, problems, stale, renderPanel, onSelect }: PreviewProps) {
  const places = placePanels(results.map((_, i) => layouts[i] ?? {}));
  const sel = selected !== null && selected < results.length ? selected : null;
  const label = sel === null ? "" : `${panelLetter(sel)}: span ${places[sel].span}, row ${places[sel].row}`;
  return (
    <div className={stale ? "hx-ed-pv stale" : "hx-ed-pv"} title={stale ? "Last valid view" : undefined}>
      <LayoutRuler placement={sel === null ? null : places[sel]} label={label} />
      {results.length === 0 ? (
        <p className="hx-ed-empty">No panels</p>
      ) : (
        <div className="hx-ed-pgrid">
          {results.map((r, i) => {
            const p = places[i];
            const problem = problems[i];
            const cls = ["hx-ed-pp", problem ? "bad" : i === sel ? "sel" : "", p.overflow ? "over" : ""];
            return (
              <section
                key={i}
                aria-label={r.title}
                className={cls.filter(Boolean).join(" ")}
                style={{ gridColumn: `${p.col} / span ${p.span}`, gridRow: `${p.row}` }}
                onClick={() => onSelect?.(i)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onSelect?.(i);
                }}
                tabIndex={0}
              >
                <div className="hx-ed-fig-h">
                  <span className="pl">{panelLetter(i)}</span>
                  <span className="t">{r.title}</span>
                  <span className="aside" title={`span ${p.span} of 12, row ${p.row}`}>
                    {p.overflow ? "over 12 columns" : `${p.span}/12`}
                  </span>
                </div>
                {problem ? <div className="hx-ed-perr">✕ {problem}</div> : renderPanel(r)}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
