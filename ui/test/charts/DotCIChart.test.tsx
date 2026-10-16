import { afterEach, describe, expect, test } from "bun:test";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { DOT_ROW_H, type DotCIRow, DotCIChart, NO_INTERVAL, dotTipRows } from "../../src/charts/DotCIChart";
import { charsFor, clip } from "../../src/charts/labels";
import { TooltipHost, hideTip } from "../../src/charts/Tooltip";

afterEach(() => act(() => hideTip()));

const rows: DotCIRow[] = [
  { id: "a", name: "lr 3e-4 · beam 10", color: "var(--c1)", mean: 0.9, lo: 0.89, hi: 0.91, seeds: [0.895, 0.905], n: 2, best: true },
  { id: "b", name: "lr 1e-3", color: "var(--c2)", mean: 0.88, lo: 0.87, hi: 0.89, n: 3 },
  { id: "c", name: "baseline", color: "var(--c3)", mean: 0.86, seeds: [0.86], n: 1 },
];
const fmt = (v: number): string => v.toFixed(3);
const num = (el: Element | null, attr: string): number => Number(el?.getAttribute(attr));

describe("DotCIChart", () => {
  test("one shared axis; height grows by one row per config; viewBox = width", () => {
    const { container } = render(<DotCIChart rows={rows} width={420} band={{ lo: 0.89, hi: 0.91 }} format={fmt} />);
    const svg = container.querySelector("svg.chart") as SVGSVGElement;
    expect(svg.getAttribute("viewBox")).toBe(`0 0 420 ${6 + 22 + 3 * DOT_ROW_H}`);
    const ticks = [...svg.querySelectorAll("text.xt")].map((t) => Number(t.textContent));
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    const step = +((ticks[1] ?? 0) - (ticks[0] ?? 0)).toPrecision(6);
    expect([0.01, 0.02, 0.025, 0.05]).toContain(step);
  });

  test("the best interval is a band behind the rows; whiskers only where an interval exists", () => {
    const { container } = render(<DotCIChart rows={rows} width={420} band={{ lo: 0.89, hi: 0.91 }} format={fmt} />);
    const band = container.querySelector("rect.band");
    const [a, , c] = [...container.querySelectorAll("g.row")];
    const whiskA = a?.querySelector("line.whisk");
    expect(num(band, "x")).toBeCloseTo(num(whiskA ?? null, "x1"), 5);
    expect(num(band, "x") + num(band, "width")).toBeCloseTo(num(whiskA ?? null, "x2"), 5);
    expect(c?.querySelector("line.whisk")).toBeNull();
    expect(container.querySelectorAll("circle.sdot").length).toBe(3);
    expect(container.querySelectorAll("circle.mdot").length).toBe(3);
  });

  test("the best value is green; long names are clipped inside the label column", () => {
    const long = { ...rows[1], id: "long", name: "x".repeat(80) } as DotCIRow;
    const { container } = render(<DotCIChart rows={[rows[0] as DotCIRow, long]} width={420} format={fmt} />);
    const vals = [...container.querySelectorAll("text.val")];
    expect(vals.map((t) => [t.textContent, t.getAttribute("class")])).toEqual([
      ["0.900", "val best"],
      ["0.880", "val"],
    ]);
    const name = [...container.querySelectorAll("text.name")][1]?.textContent ?? "";
    expect(name.endsWith("…")).toBe(true);
    expect(name.length).toBeLessThanOrEqual(charsFor(132 - 20));
  });

  test("tooltip: mean of n seeds, the interval or why there is none, Δ vs best", () => {
    const { container } = render(
      <>
        <DotCIChart rows={rows} width={420} format={fmt} />
        <TooltipHost />
      </>,
    );
    const groups = [...container.querySelectorAll("g.row")];
    fireEvent.mouseMove(groups[1] as Element, { clientX: 10, clientY: 10 });
    const text = () => [...screen.getByRole("tooltip").querySelectorAll(".r")].map((r) => r.textContent);
    expect(text()).toEqual(["0.880mean of 3 seeds", "0.870–0.89095% CI (test set)", "−0.020Δ vs best"]);
    fireEvent.mouseMove(groups[2] as Element, { clientX: 10, clientY: 10 });
    expect(text()).toEqual(["0.860mean of 1 seed", `—${NO_INTERVAL}`, "−0.040Δ vs best"]);
    expect(dotTipRows(rows[0] as DotCIRow, 0.9, fmt).at(-1)).toEqual({ value: "best", name: "Δ vs best" });
  });

  test("each row carries data-series = its id", () => {
    const { container } = render(<DotCIChart rows={rows} width={420} />);
    expect([...container.querySelectorAll("g.row")].map((g) => g.getAttribute("data-series"))).toEqual(["a", "b", "c"]);
  });

  test("focus shows the row's tooltip, blur hides it", () => {
    const { container } = render(
      <>
        <DotCIChart rows={rows} width={420} format={fmt} />
        <TooltipHost />
      </>,
    );
    const row = [...container.querySelectorAll("g.row")][0] as Element;
    fireEvent.focus(row);
    expect(screen.getByRole("tooltip").querySelector(".h")?.textContent).toBe("lr 3e-4 · beam 10");
    fireEvent.blur(row);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  test("Enter on a focused row opens it", () => {
    const opened: string[] = [];
    const { container } = render(<DotCIChart rows={rows} width={420} onOpen={(id) => opened.push(id)} />);
    fireEvent.keyDown([...container.querySelectorAll("g.row")][1] as Element, { key: "Enter" });
    expect(opened).toEqual(["b"]);
  });

  test("no scores draws a calm message, no NaN", () => {
    const { container } = render(<DotCIChart rows={[{ id: "q", name: "queued", color: "var(--c1)", mean: null }]} width={420} />);
    expect(container.textContent).toContain("no scores");
    expect(container.innerHTML).not.toContain("NaN");
  });
});

test("clip and charsFor", () => {
  expect([clip("abcdef", 4), clip("abc", 4), clip("abcdef", 1)]).toEqual(["abc…", "abc", "…"]);
  expect(charsFor(64)).toBe(9);
});
