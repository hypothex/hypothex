import { afterEach, describe, expect, test } from "bun:test";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { type BarRow, BAR_ROW_H, BarPanel, GroupedBars } from "../../src/charts/BarPanel";
import { TooltipHost, hideTip } from "../../src/charts/Tooltip";

afterEach(() => act(() => hideTip()));

const num = (el: Element | null | undefined, attr: string): number => Number(el?.getAttribute(attr));
const bars = (c: HTMLElement): Element[] => [...c.querySelectorAll("rect.bar")];
const xt = (c: HTMLElement): string[] => [...c.querySelectorAll("text.xt")].map((t) => t.textContent ?? "");

const rows: BarRow[] = [
  { id: "a", name: "a", color: "var(--c1)", value: 0.5, best: true, ci: { lo: 0.45, hi: 0.55, method: "wilson" } },
  { id: "b", name: "b", color: "var(--c2)", value: 0.25 },
];

describe("BarPanel", () => {
  test("bars start at zero, lengths are proportional, the axis is nice and starts at 0", () => {
    const { container } = render(<BarPanel rows={rows} width={400} metric="top10" />);
    const svg = container.querySelector("svg.chart") as SVGSVGElement;
    expect(svg.getAttribute("viewBox")).toBe(`0 0 400 ${4 + 20 + 2 * BAR_ROW_H}`);
    const [a, b] = bars(container);
    expect(num(a, "x")).toBe(num(b, "x"));
    expect(num(a, "width") / num(b, "width")).toBeCloseTo(2, 5);
    expect(xt(container)).toEqual(["0.0", "0.2", "0.4", "0.6"]);
  });

  test("negative values grow left from zero and the axis includes 0", () => {
    const neg: BarRow[] = [rows[0] as BarRow, { id: "c", name: "c", color: "var(--c3)", value: -0.3 }];
    const { container } = render(<BarPanel rows={neg} width={400} metric="Δ" />);
    const [a, c] = bars(container);
    expect(num(c, "x") + num(c, "width")).toBeCloseTo(num(a, "x"), 5);
    expect(xt(container)).toContain("0.0");
    expect(xt(container)[0]).toBe("−0.5");
  });

  test("best value is green, CI whiskers only where given, null is 'not reported'", () => {
    const { container } = render(
      <BarPanel rows={[...rows, { id: "n", name: "n", color: "var(--c4)", value: null }]} width={400} metric="top10" />,
    );
    expect([...container.querySelectorAll("text.val")].map((t) => [t.textContent, t.getAttribute("class")])).toEqual([
      ["0.5", "val best"],
      ["0.25", "val"],
    ]);
    expect(container.querySelectorAll("line.ci").length).toBe(3);
    expect(container.querySelector("text.none")?.textContent).toBe("not reported");
  });

  test("each row carries its run id for hide/show", () => {
    const { container } = render(<BarPanel rows={rows} width={400} metric="top10" />);
    expect([...container.querySelectorAll("g.row")].map((g) => g.getAttribute("data-series"))).toEqual(["a", "b"]);
  });

  test("highlight dims the other rows", () => {
    const { container } = render(<BarPanel rows={rows} width={400} metric="top10" highlight="b" />);
    expect([...container.querySelectorAll("g.row")].map((g) => g.getAttribute("class"))).toEqual(["row dim", "row"]);
  });

  test("long names are clipped to 22 chars and the label column stops at 150 px", () => {
    const long = [{ ...rows[0], name: "a".repeat(60) } as BarRow];
    const { container } = render(<BarPanel rows={long} width={400} metric="m" />);
    expect(container.querySelector("text.lbl")?.textContent).toBe(`${"a".repeat(21)}…`);
    expect(num(bars(container)[0], "x")).toBe(150);
  });

  test("tooltip: full name, value and interval", () => {
    const long = [{ ...rows[0], name: "a".repeat(60) } as BarRow];
    const { container } = render(
      <>
        <BarPanel rows={long} width={400} metric="top10" />
        <TooltipHost />
      </>,
    );
    fireEvent.mouseMove(container.querySelector("g.row") as Element, { clientX: 5, clientY: 5 });
    const tip = screen.getByRole("tooltip");
    expect(tip.querySelector(".h")?.textContent).toBe("a".repeat(60));
    expect([...tip.querySelectorAll(".r")].map((r) => r.textContent)).toEqual(["0.5top10", "0.45–0.5595% CI · wilson"]);
  });

  test("text size does not follow the width", () => {
    for (const w of [330, 1200]) {
      const { container, unmount } = render(<BarPanel rows={rows} width={w} metric="m" />);
      const svg = container.querySelector("svg.chart") as SVGSVGElement;
      expect([svg.getAttribute("width"), svg.getAttribute("viewBox")?.split(" ")[2]]).toEqual([String(w), String(w)]);
      expect([...svg.querySelectorAll("text")].every((t) => t.getAttribute("font-size") === null)).toBe(true);
      unmount();
    }
  });

  test("no values at all still draws rows without NaN", () => {
    const { container } = render(<BarPanel rows={[{ id: "n", name: "n", color: "var(--c1)", value: null }]} width={300} metric="m" />);
    expect(container.innerHTML).not.toContain("NaN");
  });

  test("no rows draws a calm 'no scores'", () => {
    const { container } = render(<BarPanel rows={[]} width={300} metric="m" />);
    expect(container.querySelector("text.none")?.textContent).toBe("no scores");
    expect(container.innerHTML).not.toContain("NaN");
  });
});

describe("GroupedBars", () => {
  test("one zero-based bar per run inside each dataset; the dataset's best is green", () => {
    const values: Record<string, Record<string, number | null>> = {
      "test-a": { r1: 0.8, r2: 0.6 },
      "test-b": { r1: 0.4, r2: null },
    };
    const { container } = render(
      <GroupedBars
        categories={["test-a", "test-b"]}
        series={[
          { id: "r1", name: "lr 3e-4", color: "var(--c1)" },
          { id: "r2", name: "lr 1e-3", color: "var(--c2)" },
        ]}
        valueOf={(c, s) => values[c]?.[s] ?? null}
        best={(c) => (c === "test-a" ? 0.8 : null)}
        width={500}
      />,
    );
    const rects = bars(container);
    expect(rects.length).toBe(3);
    expect(new Set(rects.map((r) => r.getAttribute("x"))).size).toBe(1);
    expect(xt(container)[0]).toBe("0.0");
    expect([...container.querySelectorAll("text.cat")].map((t) => t.textContent)).toEqual(["test-a", "test-b"]);
    expect(container.querySelector("text.val.best")?.textContent).toBe("0.8");
    expect([...container.querySelectorAll("g.row")].map((g) => g.getAttribute("data-series"))).toEqual(["r1", "r2", "r1", "r2"]);
  });

  test("long dataset names clip at 16 chars; the tooltip names the run", () => {
    const { container } = render(
      <>
        <GroupedBars
          categories={["d".repeat(40)]}
          series={[{ id: "r1", name: "lr 3e-4", color: "var(--c1)" }]}
          valueOf={() => 0.5}
          width={500}
        />
        <TooltipHost />
      </>,
    );
    expect(container.querySelector("text.cat")?.textContent).toBe(`${"d".repeat(15)}…`);
    fireEvent.mouseMove(container.querySelector("g.row") as Element, { clientX: 5, clientY: 5 });
    const tip = screen.getByRole("tooltip");
    expect(tip.querySelector(".h")?.textContent).toBe("d".repeat(40));
    expect([...tip.querySelectorAll(".r")].map((r) => r.textContent)).toEqual(["0.5lr 3e-4"]);
  });

  test("no datasets or no runs draws a calm 'no scores'", () => {
    for (const [categories, series] of [
      [[], [{ id: "r1", name: "r1", color: "var(--c1)" }]],
      [["test-a"], []],
    ] as const) {
      const { container, unmount } = render(
        <GroupedBars categories={categories} series={series} valueOf={() => null} width={400} />,
      );
      expect(container.querySelector("text.none")?.textContent).toBe("no scores");
      expect(container.innerHTML).not.toContain("NaN");
      unmount();
    }
  });
});
