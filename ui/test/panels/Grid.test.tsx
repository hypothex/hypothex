import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { cellFill, cellKey, GridPanel, type GridRow, gridLayout } from "../../src/panels/Grid";

afterEach(cleanup);

const ROWS: GridRow[] = [
  { item_id: "t1", group_id: "gA", value: 1 },
  { item_id: "t2", group_id: "gA", value: 2 / 3 },
  { item_id: "t3", group_id: "gA", value: 1 / 3 },
  { item_id: "t1", group_id: "gB", value: 1 },
  { item_id: "t2", group_id: "gB", value: 0 },
  { item_id: "t3", group_id: "gB", value: 0 },
];
// mean per item: t3 = 1/6, t2 = 1/3, t1 = 1 -> hardest first: t3, t2, t1
const META = {
  items: ["t3", "t2", "t1"],
  groups: [
    { group_id: "gA", label: "mcts" },
    { group_id: "gB", label: "greedy" },
  ],
};

const grid = (meta: Record<string, unknown>, rows: GridRow[] = ROWS): PanelResult => ({
  type: "grid",
  title: "Per target",
  rows: rows as unknown as Record<string, unknown>[],
  meta,
});

describe("cellFill", () => {
  test("paper at 0, ink at 1, mixed in between", () => {
    expect(cellFill(0)).toBe("var(--paper-2)");
    expect(cellFill(1)).toBe("var(--ink)");
    expect(cellFill(1 / 3)).toBe("color-mix(in srgb, var(--ink) 29%, var(--paper))");
    expect(cellFill(2 / 3)).toBe("color-mix(in srgb, var(--ink) 58%, var(--paper))");
    expect(cellFill(0.5)).toBe("color-mix(in srgb, var(--ink) 44%, var(--paper))");
  });
});

describe("gridLayout", () => {
  test("uses meta order when given", () => {
    const g = gridLayout(ROWS, META);
    expect(g.items).toEqual(["t3", "t2", "t1"]);
    expect(g.groups.map((x) => x.label)).toEqual(["mcts", "greedy"]);
    expect(g.cells.get(cellKey("gA", "t2"))).toBeCloseTo(2 / 3, 12);
  });

  test("derives difficulty order and group ids without meta", () => {
    const g = gridLayout(ROWS, {});
    expect(g.items).toEqual(["t3", "t2", "t1"]);
    expect(g.groups).toEqual([
      { group_id: "gA", label: "gA" },
      { group_id: "gB", label: "gB" },
    ]);
  });

  test("appends items and groups missing from meta", () => {
    const g = gridLayout([...ROWS, { item_id: "t4", group_id: "gC", value: 0.5 }], META);
    expect(g.items).toEqual(["t3", "t2", "t1", "t4"]);
    expect(g.groups.map((x) => x.group_id)).toEqual(["gA", "gB", "gC"]);
  });
});

describe("GridPanel", () => {
  test("one cell per row, columns in meta order, fills by value", () => {
    const { container } = render(<GridPanel result={grid(META)} />);
    expect(container.querySelectorAll("rect[data-item]").length).toBe(6);
    const gA = container.querySelector('[data-group="gA"]') as Element;
    const cells = [...gA.querySelectorAll("rect[data-item]")] as SVGElement[];
    expect(cells.map((c) => c.getAttribute("data-item"))).toEqual(["t3", "t2", "t1"]);
    expect(cells.map((c) => c.style.fill)).toEqual([
      "color-mix(in srgb, var(--ink) 29%, var(--paper))",
      "color-mix(in srgb, var(--ink) 58%, var(--paper))",
      "var(--ink)",
    ]);
    // x = 150 + j * (720 - 150) / 3
    expect(cells.map((c) => Number(c.getAttribute("x")))).toEqual([150, 340, 530]);
  });

  test("group labels in order with solved counts", () => {
    const { container } = render(<GridPanel result={grid(META)} />);
    const labels = [...container.querySelectorAll("[data-group]")].map(
      (g) => g.querySelector("text")?.textContent,
    );
    expect(labels).toEqual(["mcts", "greedy"]);
    const solved = [...container.querySelectorAll("[data-solved]")].map((t) =>
      t.getAttribute("data-solved"),
    );
    expect(solved).toEqual(["2", "1"]);
  });

  test("cell tooltips and axis ends", () => {
    const { container } = render(<GridPanel result={grid(META)} />);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain("t2\nmcts: 0.667 of seeds solved");
    expect(screen.getByText("hard")).toBeTruthy();
    expect(screen.getByText("easy")).toBeTruthy();
  });

  test("empty result says so", () => {
    render(<GridPanel result={grid({}, [])} />);
    expect(screen.getByText("No items")).toBeTruthy();
  });
});
