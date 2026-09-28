import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LayoutRuler, type PanelResult, Preview, panelLetter, placePanels } from "../../src/editor/Preview";

afterEach(cleanup);

describe("placePanels", () => {
  test("places explicit rows left to right (the custom_view mockup layout)", () => {
    const got = placePanels([
      { span: 12, row: 1 },
      { span: 7, row: 2 },
      { span: 5, row: 2 },
      { span: 8, row: 3 },
      { span: 4, row: 3 },
    ]);
    expect(got).toEqual([
      { col: 1, span: 12, row: 1, overflow: false },
      { col: 1, span: 7, row: 2, overflow: false },
      { col: 8, span: 5, row: 2, overflow: false },
      { col: 1, span: 8, row: 3, overflow: false },
      { col: 9, span: 4, row: 3, overflow: false },
    ]);
  });

  test("flows panels without a row and wraps when a row is full", () => {
    expect(placePanels([{ span: 6 }, { span: 6 }, {}, { span: 4 }])).toEqual([
      { col: 1, span: 6, row: 1, overflow: false },
      { col: 7, span: 6, row: 1, overflow: false },
      { col: 1, span: 12, row: 2, overflow: false },
      { col: 1, span: 4, row: 3, overflow: false },
    ]);
  });

  test("flows around explicit rows and never moves back (CSS sparse placement)", () => {
    expect(placePanels([{ span: 6, row: 1 }, { span: 6 }])[1]).toEqual({
      col: 7,
      span: 6,
      row: 1,
      overflow: false,
    });
    // The 8-wide panel cannot fit beside row 1's 6; the next 6-wide one cannot fit in
    // row 2's 4 free columns and does not go back to row 1.
    expect(placePanels([{ span: 6, row: 1 }, { span: 8 }, { span: 6 }]).slice(1)).toEqual([
      { col: 1, span: 8, row: 2, overflow: false },
      { col: 1, span: 6, row: 3, overflow: false },
    ]);
  });

  test("flags a row wider than 12 columns and clamps spans to 1..12", () => {
    expect(placePanels([{ span: 7, row: 2 }, { span: 7, row: 2 }])[1]).toEqual({
      col: 6,
      span: 7,
      row: 2,
      overflow: true,
    });
    expect(placePanels([{ span: 20 }, { span: 0, row: 3 }]).map((p) => p.span)).toEqual([12, 1]);
  });
});

test("panelLetter counts a, b, c", () => {
  expect([0, 1, 2, 25].map(panelLetter)).toEqual(["a", "b", "c", "z"]);
});

describe("LayoutRuler", () => {
  test("lights the selected panel's columns", () => {
    const { container } = render(
      <LayoutRuler placement={{ col: 8, span: 5, row: 2, overflow: false }} label="c: span 5, row 2" />,
    );
    const lit = [...container.querySelectorAll(".hx-ed-ruler span.on")].map((s) => s.textContent);
    expect(lit).toEqual(["8", "9", "10", "11", "12"]);
    expect(screen.getByTestId("ruler-label").textContent).toBe("c: span 5, row 2");
  });

  test("lights nothing without a selection", () => {
    const { container } = render(<LayoutRuler placement={null} label="" />);
    expect(container.querySelectorAll(".hx-ed-ruler span").length).toBe(12);
    expect(container.querySelectorAll(".hx-ed-ruler span.on").length).toBe(0);
  });
});

const RESULTS: PanelResult[] = [
  { type: "stat_strip", title: "Best config", rows: [], meta: {} },
  { type: "scatter", title: "Length vs time", rows: [], meta: {} },
  { type: "markdown", title: "Note", rows: [], meta: { text: "hi" } },
];
const LAYOUTS = [{ span: 12, row: 1 }, { span: 5, row: 2 }, { span: 7, row: 2 }];

describe("Preview", () => {
  test("draws lettered panels at their grid cells through renderPanel", () => {
    const onSelect = mock((_i: number) => {});
    render(
      <Preview
        results={RESULTS}
        layouts={LAYOUTS}
        selected={2}
        problems={{}}
        stale={false}
        renderPanel={(r) => <p>{`${r.type} body`}</p>}
        onSelect={onSelect}
      />,
    );
    const note = screen.getByRole("region", { name: "Note" });
    expect(note.className).toBe("hx-ed-pp sel");
    expect(note.style.gridColumn).toBe("6 / span 7");
    expect(note.style.gridRow).toBe("2");
    expect(note.textContent).toBe("cNote7/12markdown body");
    expect(screen.getByTestId("ruler-label").textContent).toBe("c: span 7, row 2");
    fireEvent.click(screen.getByRole("region", { name: "Best config" }));
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  test("replaces a panel with its validation problem and marks a stale preview", () => {
    const { container } = render(
      <Preview
        results={RESULTS}
        layouts={LAYOUTS}
        selected={null}
        problems={{ 1: "unknown metric route_length, ln 13" }}
        stale
        renderPanel={(r) => <p>{`${r.type} body`}</p>}
      />,
    );
    const bad = screen.getByRole("region", { name: "Length vs time" });
    expect(bad.className).toBe("hx-ed-pp bad");
    expect(bad.textContent).toContain("✕ unknown metric route_length, ln 13");
    expect(bad.textContent).not.toContain("scatter body");
    expect((container.firstChild as HTMLElement).className).toBe("hx-ed-pv stale");
    expect(screen.getByTestId("ruler-label").textContent).toBe("");
  });

  test("says so when the view has no panels", () => {
    render(<Preview results={[]} layouts={[]} selected={null} problems={{}} stale={false} renderPanel={() => null} />);
    expect(screen.getByText("No panels")).toBeDefined();
  });
});
