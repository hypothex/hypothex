import { afterEach, describe, expect, mock, test } from "bun:test";
import { diagnosticCount } from "@codemirror/lint";
import { EditorState, Text } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { act, cleanup, render } from "@testing-library/react";
import { createRef } from "react";
import {
  issuesToDiagnostics,
  outlineView,
  panelAtLine,
  type ValidationIssue,
  YamlEditor,
  type YamlEditorHandle,
} from "../../src/editor/YamlEditor";

afterEach(cleanup);

// Lines: 1 title, 2 runs, 3 panels:, 4-7 panel a, 8 blank, 9-15 panel b, 16 "" (final newline).
const SAMPLE = [
  "title: route quality",
  "runs: {status: finished}",
  "panels:",
  "  - type: stat_strip",
  "    title: Best config",
  "    data: {metrics: [solved], pick: best}",
  "    layout: {span: 12, row: 1}",
  "",
  "  - type: scatter",
  '    title: "Length vs time"  # c',
  "    data:",
  "      x: solve_time",
  "      y: route_length@v1/median",
  "      title: not the panel title",
  "    layout: {span: 5, row: 2}",
  "",
].join("\n");

// The exact message and suggestion the backend sends (backend plan Task 16): no quotes, and
// a metric suggestion is the whole corrected reference.
const BAD_METRIC: ValidationIssue = {
  line: 13,
  path: "panels[1].data.y",
  message: "unknown metric route_length",
  suggestion: "route_len@v1/median",
};

describe("outlineView", () => {
  test("finds the list, its indent, and each panel's lines and title", () => {
    expect(outlineView(SAMPLE)).toEqual({
      panelsLine: 3,
      emptyList: false,
      itemIndent: "  ",
      endLine: 17,
      panels: [
        { index: 0, title: "Best config", startLine: 4, endLine: 8 },
        { index: 1, title: "Length vs time", startLine: 9, endLine: 16 },
      ],
    });
  });

  test("stops the list at the next top-level key", () => {
    const text = "panels:\n  - type: markdown\n    text: hi\nruns: {status: finished}\n";
    const outline = outlineView(text);
    expect(outline.endLine).toBe(4);
    expect(outline.panels).toEqual([{ index: 0, title: "", startLine: 2, endLine: 3 }]);
  });

  test("handles zero-indent items, the empty flow list, and no list", () => {
    const flat = outlineView("title: t\npanels:\n- type: markdown\n  title: n\n");
    expect(flat.itemIndent).toBe("");
    expect(flat.panels).toEqual([{ index: 0, title: "n", startLine: 3, endLine: 5 }]);
    const empty = outlineView("title: t\nfrom: training\npanels: []\n");
    expect([empty.panelsLine, empty.emptyList, empty.panels]).toEqual([3, true, []]);
    expect(outlineView("title: t").panelsLine).toBeNull();
  });

  test("panelAtLine maps a cursor line to its panel", () => {
    const outline = outlineView(SAMPLE);
    expect(panelAtLine(outline, 2)).toBeNull();
    expect(panelAtLine(outline, 6)?.title).toBe("Best config");
    expect(panelAtLine(outline, 13)?.index).toBe(1);
  });
});

describe("issuesToDiagnostics", () => {
  const doc = Text.of(SAMPLE.split("\n"));

  test("marks the whole metric reference and the fix replaces all of it", () => {
    const [d] = issuesToDiagnostics(doc, [BAD_METRIC]);
    // "      y: route_length@v1/median": the reference starts at column 9, 22 characters long.
    expect(d.from - doc.line(13).from).toBe(9);
    expect(d.to - d.from).toBe(22);
    expect(d.severity).toBe("error");
    expect(d.message).toBe("unknown metric route_length (panels[1].data.y)");
    expect(d.actions?.map((a) => a.name)).toEqual(["use route_len@v1/median"]);
    const view = new EditorView({ state: EditorState.create({ doc: SAMPLE }) });
    d.actions?.[0]?.apply(view, d.from, d.to);
    expect(view.state.doc.line(13).text).toBe("      y: route_len@v1/median");
    view.destroy();
  });

  test("narrows the backend's unquoted key, type and scale names to their token", () => {
    const text = Text.of([
      "title: t",
      "runs: {stauts: finished}",
      "panels:",
      "  - type: leaderbord",
      "    scale: zzz",
      "    data: {source: runs, fields: [stauts]}",
    ]);
    const [key, type, scale, field] = issuesToDiagnostics(text, [
      { line: 2, path: "runs.stauts", message: "unknown key stauts", suggestion: "status" },
      { line: 4, path: "panels[0].type", message: "unknown type leaderbord", suggestion: "leaderboard" },
      { line: 5, path: "panels[0].scale", message: "unknown scale zzz; expected one of linear, log", suggestion: null },
      { line: 6, path: "panels[0].data.fields[0]", message: "unknown field stauts in runs", suggestion: "status" },
    ]);
    const marked = (d: typeof key) => text.sliceString(d.from, d.to);
    expect([marked(key), marked(type), marked(scale), marked(field)]).toEqual(["stauts", "leaderbord", "zzz", "stauts"]);
    expect(key.actions?.map((a) => a.name)).toEqual(["use status"]);
    expect(type.actions?.map((a) => a.name)).toEqual(["use leaderboard"]);
    expect(scale.actions).toBeUndefined();
  });

  test("marks the whole line without a token, line 1 without a line, the last line past the end", () => {
    const issues: ValidationIssue[] = [
      { line: 7, path: "panels[0].layout.span", message: "span must be 1..12" },
      { line: null, path: "", message: "title: field required" },
      { line: 99, path: "panels", message: "bad" },
    ];
    const [span, noLine, past] = issuesToDiagnostics(doc, issues);
    // "    layout: {span: 12, row: 1}": marked from the first non-space character.
    expect([span.from, span.to]).toEqual([doc.line(7).from + 4, doc.line(7).to]);
    expect(span.actions).toBeUndefined();
    expect([noLine.from, noLine.to, noLine.message]).toEqual([0, 20, "title: field required"]);
    expect([past.from, past.to]).toEqual([doc.length, doc.length]);
  });
});

describe("YamlEditor", () => {
  test("shows the text, marks issues, applies insertions, and follows value changes", () => {
    const ref = createRef<YamlEditorHandle>();
    const onChange = mock((_text: string) => {});
    const onCursorLine = mock((_line: number) => {});
    const { rerender } = render(
      <YamlEditor
        ref={ref}
        value={SAMPLE}
        onChange={onChange}
        issues={[BAD_METRIC]}
        onCursorLine={onCursorLine}
      />,
    );
    const view = ref.current?.view();
    expect(view?.state.doc.toString()).toBe(SAMPLE);
    expect(diagnosticCount(view!.state)).toBe(1);

    act(() => ref.current?.applyInsertion(() => ({ from: 0, to: 0, insert: "# hi\n", line: 1 })));
    expect(onChange).toHaveBeenLastCalledWith(`# hi\n${SAMPLE}`);
    expect(view?.state.selection.main.head).toBe(4);

    act(() => ref.current?.goToLine(10));
    expect(onCursorLine).toHaveBeenLastCalledWith(10);

    rerender(
      <YamlEditor ref={ref} value={"title: x\n"} onChange={onChange} issues={[]} onCursorLine={onCursorLine} />,
    );
    expect(view?.state.doc.toString()).toBe("title: x\n");
    expect(diagnosticCount(view!.state)).toBe(0);
  });
});
