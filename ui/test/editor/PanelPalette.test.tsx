import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PALETTE, PanelPalette, type PanelType, panelSnippet, planInsert } from "../../src/editor/PanelPalette";

afterEach(cleanup);

function apply(text: string, cursorLine: number, type: PanelType, metric = "acc") {
  const plan = planInsert(text, cursorLine, panelSnippet(type, metric));
  return { text: text.slice(0, plan.from) + plan.insert + text.slice(plan.to), line: plan.line };
}

const TWO = [
  "title: t",
  "panels:",
  "  - type: stat_strip",
  "    title: a",
  "  - type: markdown",
  "    title: b",
  "    text: hi",
  "",
].join("\n");

describe("panelSnippet", () => {
  test("fills metric slots and ends with a full-width layout", () => {
    expect(panelSnippet("scatter", "solved")).toEqual([
      "- type: scatter",
      "  title: New scatter",
      "  data: {x: solved, y: solved}",
      "  pareto: {x: min, y: max}",
      "  layout: {span: 12}",
    ]);
    expect(panelSnippet("markdown", "x")).toEqual([
      "- type: markdown",
      "  title: New markdown",
      "  text: |",
      "    Note.",
      "  layout: {span: 12}",
    ]);
  });

  test("has a snippet for every palette entry", () => {
    for (const p of PALETTE) expect(panelSnippet(p.type, "m")[0]).toBe(`- type: ${p.type}`);
  });
});

describe("planInsert", () => {
  test("goes after the panel under the cursor", () => {
    const out = apply(TWO, 4, "markdown");
    expect(out.text).toBe(
      [
        "title: t",
        "panels:",
        "  - type: stat_strip",
        "    title: a",
        "  - type: markdown",
        "    title: New markdown",
        "    text: |",
        "      Note.",
        "    layout: {span: 12}",
        "  - type: markdown",
        "    title: b",
        "    text: hi",
        "",
      ].join("\n"),
    );
    expect(out.line).toBe(5);
  });

  test("goes to the end of the list when the cursor is outside every panel", () => {
    const out = apply(TWO, 1, "grid");
    expect(out.text).toBe(
      `${TWO}  - type: grid\n    title: New grid\n    data: {metrics: [acc]}\n    layout: {span: 12}\n`,
    );
    expect(out.line).toBe(8);
  });

  test("stops before the next top-level key", () => {
    const text = "panels:\n  - type: markdown\n    text: hi\nruns: {status: finished}\n";
    const out = apply(text, 1, "trace");
    expect(out.text).toBe(
      "panels:\n  - type: markdown\n    text: hi\n" +
        "  - type: trace\n    title: New trace\n    data: {source: traces}\n    layout: {span: 12}\n" +
        "runs: {status: finished}\n",
    );
    expect(out.line).toBe(4);
  });

  test("turns `panels: []` into a block list", () => {
    const text = "title: t\nfrom: training\npanels: []\n";
    const plan = planInsert(text, 1, panelSnippet("leaderboard", "loss"));
    // "title: t\n" is 9 characters and "from: training\n" is 15, so the key starts at 24.
    expect([plan.from, plan.to, plan.line]).toEqual([24, 34, 4]);
    expect(apply(text, 1, "leaderboard", "loss").text).toBe(
      "title: t\nfrom: training\npanels:\n  - type: leaderboard\n    title: New leaderboard\n" +
        "    data: {metrics: [loss]}\n    noise: [seed, test_set]\n    layout: {span: 12}\n",
    );
  });

  test("adds a `panels:` key when there is none, fixing a missing final newline", () => {
    const out = apply("title: t", 1, "stat_strip");
    expect(out.text).toBe(
      "title: t\npanels:\n  - type: stat_strip\n    title: New stat strip\n" +
        "    data: {metrics: [acc], pick: best}\n    layout: {span: 12}\n",
    );
    expect(out.line).toBe(3);
  });

  test("keeps a zero-indent list at zero indent", () => {
    const out = apply("panels:\n- type: markdown\n  text: hi\n", 2, "trace");
    expect(out.text).toBe(
      "panels:\n- type: markdown\n  text: hi\n- type: trace\n  title: New trace\n" +
        "  data: {source: traces}\n  layout: {span: 12}\n",
    );
    expect(out.line).toBe(4);
  });
});

describe("PanelPalette", () => {
  test("shows one button per type and reports the clicked type", () => {
    const onInsert = mock((_t: PanelType) => {});
    render(<PanelPalette onInsert={onInsert} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      "stat strip",
      "leaderboard",
      "curves",
      "scatter",
      "distribution",
      "grid",
      "table",
      "trace",
      "markdown",
      "vega-lite",
    ]);
    const vega = screen.getByRole("button", { name: "vega-lite" });
    expect(vega.getAttribute("title")).toBe("vega-lite: any Vega-Lite spec over a source");
    fireEvent.click(vega);
    expect(onInsert).toHaveBeenCalledWith("vega_lite");
  });
});
