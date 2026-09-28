import type { PanelType } from "../api/models";
import { type Insertion, outlineView, panelAtLine } from "./YamlEditor";

/** Panel types a view may use (contract 1.4 `PanelType`, from the API models). */
export type { PanelType };

export interface PaletteEntry {
  type: PanelType;
  label: string;
  hint: string;
}

/** Palette buttons, in the mockup's order. `hint` is the button tooltip. */
export const PALETTE: readonly PaletteEntry[] = [
  { type: "stat_strip", label: "stat strip", hint: "a row of headline numbers" },
  { type: "leaderboard", label: "leaderboard", hint: "seed groups ranked, seed and test-set noise" },
  { type: "curves", label: "curves", hint: "metric by step, one line per run" },
  { type: "scatter", label: "scatter", hint: "two metrics per group, optional Pareto front" },
  { type: "distribution", label: "distribution", hint: "ECDF with p50, p95, p99" },
  { type: "grid", label: "grid", hint: "items by groups, fraction of seeds solved" },
  { type: "table", label: "table", hint: "rows from a source, chosen fields" },
  { type: "trace", label: "trace", hint: "one agent attempt, turn by turn" },
  { type: "markdown", label: "markdown", hint: "a note" },
  { type: "vega_lite", label: "vega-lite", hint: "any Vega-Lite spec over a source" },
];

/**
 * YAML lines for a new panel, relative to the list indent.
 *
 * `metric` fills metric slots (the task's primary metric name); the user edits
 * the rest. Every field is a contract `PanelSpec` field, so the snippet
 * validates whenever `metric` is known.
 */
export function panelSnippet(type: PanelType, metric: string): string[] {
  const label = PALETTE.find((p) => p.type === type)?.label ?? type;
  const body: Record<PanelType, string[]> = {
    stat_strip: [`  data: {metrics: [${metric}], pick: best}`],
    leaderboard: [`  data: {metrics: [${metric}]}`, "  noise: [seed, test_set]"],
    curves: [`  data: {metrics: [${metric}]}`],
    scatter: [`  data: {x: ${metric}, y: ${metric}}`, "  pareto: {x: min, y: max}"],
    distribution: [`  data: {metrics: [${metric}]}`, "  scale: linear"],
    grid: [`  data: {metrics: [${metric}]}`],
    table: ["  data: {source: runs, fields: [run_id, status, created_by]}"],
    trace: ["  data: {source: traces}"],
    markdown: ["  text: |", "    Note."],
    vega_lite: [
      "  data: {source: runs, fields: [status]}",
      "  spec:",
      "    mark: bar",
      "    encoding:",
      "      x: {field: status, type: nominal}",
      "      y: {aggregate: count, type: quantitative}",
    ],
  };
  return [`- type: ${type}`, `  title: New ${label}`, ...body[type], "  layout: {span: 12}"];
}

/**
 * Plan where a snippet goes: after the panel under the cursor.
 *
 * With the cursor outside every panel the snippet goes at the end of the
 * `panels:` list. `panels: []` becomes a block list; a view with no `panels:`
 * key gets one at the end.
 */
export function planInsert(text: string, cursorLine: number, snippet: string[]): Insertion {
  const outline = outlineView(text);
  const lines = text.split("\n");
  const startOf = (line: number) => lines.slice(0, line - 1).reduce((n, l) => n + l.length + 1, 0);
  const indent = outline.itemIndent;
  const block = snippet.map((l) => indent + l).join("\n");
  const tail = text === "" || text.endsWith("\n") ? "" : "\n";
  let from: number;
  let to: number;
  let insert: string;
  if (outline.panelsLine === null) {
    from = to = text.length;
    insert = `${tail}panels:\n${block}\n`;
  } else if (outline.emptyList) {
    from = startOf(outline.panelsLine);
    to = from + lines[outline.panelsLine - 1].length;
    insert = `panels:\n${block}`;
  } else {
    const inside = panelAtLine(outline, cursorLine);
    const target = inside ? inside.endLine + 1 : outline.endLine;
    if (target > lines.length) {
      from = to = text.length;
      insert = `${tail}${block}\n`;
    } else {
      from = to = startOf(target);
      insert = `${block}\n`;
    }
  }
  const next = text.slice(0, from) + insert + text.slice(to);
  const itemAt = from + insert.indexOf(`${indent}- type:`);
  return { from, to, insert, line: next.slice(0, itemAt).split("\n").length };
}

export interface PanelPaletteProps {
  onInsert: (type: PanelType) => void;
}

/** "Insert" row: one button per panel type. */
export function PanelPalette({ onInsert }: PanelPaletteProps) {
  return (
    <div className="hx-ed-ins">
      <span>Insert</span>
      <div className="hx-ed-lib">
        {PALETTE.map((p) => (
          <button key={p.type} type="button" title={`${p.label}: ${p.hint}`} onClick={() => onInsert(p.type)}>
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
