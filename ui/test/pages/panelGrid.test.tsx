import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { NavigateContext } from "../../src/pages/components/links";
import { PanelGrid, PanelRegistryContext, clampSpan, panelGridStyle } from "../../src/pages/components/PanelGrid";
import type { PanelResult } from "../../src/pages/components/types";
import { fakeRegistry } from "./helpers";

afterEach(cleanup);

const results: PanelResult[] = [
  { type: "markdown", title: "Note", rows: [], meta: { text: "hi" } },
  { type: "curves", title: "", rows: [{}, {}], meta: { warnings: ["metric lr not logged"] } },
  { type: "vega_lite", title: "Depth", rows: [], meta: {} },
];

test("clampSpan keeps spans in 1..12; a full span takes the row, others one cell", () => {
  expect([undefined, 0, 4, 12, 13, 5.6].map(clampSpan)).toEqual([12, 1, 4, 12, 12, 6]);
  expect([panelGridStyle(undefined), panelGridStyle(12), panelGridStyle(8)]).toEqual([
    { gridColumn: "1 / -1" },
    { gridColumn: "1 / -1" },
    undefined,
  ]);
});

test("panels sit in v5 panel chrome on the min-330 grid, named by title, no letters", () => {
  const { container } = render(
    <PanelRegistryContext.Provider value={fakeRegistry(["markdown", "curves"])}>
      <PanelGrid
        results={results}
        specs={[
          { type: "markdown", layout: { span: 4, row: 2 } },
          { type: "curves", title: "Loss", layout: { span: 8, row: null } },
          { type: "vega_lite" },
        ]}
      />
    </PanelRegistryContext.Provider>,
  );
  expect(container.firstElementChild?.className).toBe("pgrid panel-grid");
  expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual(["Note", "Loss", "Depth"]);
  const note = screen.getByRole("region", { name: "Note" });
  expect([note.className, note.style.gridColumn, note.style.gridRow]).toEqual(["panel", "", ""]);
  expect(note.querySelector(".pl")).toBeNull();
  expect(within(note).getByTestId("panel-markdown").textContent).toBe("Note:0");
  const loss = screen.getByRole("region", { name: "Loss" });
  const warn = loss.querySelector(".aside span") as HTMLElement;
  expect([warn.textContent, warn.getAttribute("title")]).toEqual(["⚠ 1", "metric lr not logged"]);
  const depth = screen.getByRole("region", { name: "Depth" });
  expect(depth.style.gridColumn).toBe("1 / -1");
  expect(within(depth).getByRole("alert").textContent).toBe("Unknown panel type: vega_lite");
});

test("a panel whose query failed shows the server's reason, not its empty state", () => {
  const failed: PanelResult[] = [
    { type: "scatter", title: "Cost vs quality", rows: [], meta: { error: "scatter panel needs data.x and data.y" } },
    { type: "markdown", title: "Note", rows: [], meta: { text: "hi" } },
  ];
  render(
    <PanelRegistryContext.Provider value={fakeRegistry(["scatter", "markdown"])}>
      <PanelGrid results={failed} />
    </PanelRegistryContext.Provider>,
  );
  const bad = screen.getByRole("region", { name: "Cost vs quality" });
  expect(within(bad).getByRole("alert").textContent).toBe("scatter panel needs data.x and data.y");
  expect(within(bad).queryByTestId("panel-scatter")).toBeNull();
  expect(within(screen.getByRole("region", { name: "Note" })).getByTestId("panel-markdown").textContent).toBe("Note:0");
});

test("a panel that throws shows its error and the other panels still draw", () => {
  const Broken = () => {
    throw new Error("bad rows");
  };
  const quiet = console.error;
  console.error = () => {};
  try {
    render(
      <PanelRegistryContext.Provider value={{ ...fakeRegistry(["markdown"]), curves: Broken }}>
        <PanelGrid results={results.slice(0, 2)} />
      </PanelRegistryContext.Provider>,
    );
  } finally {
    console.error = quiet;
  }
  expect(within(screen.getByRole("region", { name: "curves" })).getByRole("alert").textContent).toBe("Panel failed: bad rows");
  expect(within(screen.getByRole("region", { name: "Note" })).getByTestId("panel-markdown").textContent).toBe("Note:0");
});

test("a plain run link inside a panel navigates in-app", () => {
  const navigate = mock((_href: string) => {});
  const RunLink = ({ result }: { result: PanelResult }) => <a href="/r/r9">{result.title}</a>;
  render(
    <NavigateContext.Provider value={navigate}>
      <PanelRegistryContext.Provider value={{ table: RunLink }}>
        <PanelGrid results={[{ type: "table", title: "open r9", rows: [], meta: {} }]} />
      </PanelRegistryContext.Provider>
    </NavigateContext.Provider>,
  );
  const link = screen.getByRole("link", { name: "open r9" });
  expect(fireEvent.click(link)).toBe(false);
  expect(navigate.mock.calls).toEqual([["/r/r9"]]);
});
