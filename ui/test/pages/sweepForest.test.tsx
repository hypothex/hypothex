import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { SweepForest, type SweepForestProps } from "../../src/pages/components/SweepForest";
import { type SweepCellRow, cellTip, parseCell, parseCells, seedValues } from "../../src/pages/components/SweepModel";
import { renderWithClient } from "./helpers";
import { CELL_D, RAW_CELLS, makeSweepBoard } from "./sweepFixtures";

afterEach(cleanup);

const BOARD = makeSweepBoard();
const NAMES = ["lr", "beam"];

function renderForest(over: Partial<SweepForestProps> = {}) {
  return renderWithClient(
    <SweepForest
      cells={parseCells(RAW_CELLS)}
      best={parseCell(CELL_D)}
      names={NAMES}
      metric="top1"
      axisLabel="top1 v1"
      higherIsBetter
      maxSeeds={2}
      seedsOf={(c) => seedValues(c, BOARD)}
      {...over}
    />,
  );
}

describe("SweepForest", () => {
  test("one row per scored cell, best first, best label bold", () => {
    const { container } = renderForest();
    const rows = [...container.querySelectorAll("g.frow")];
    expect(rows.map((g) => g.getAttribute("data-label"))).toEqual(["3e-4, 10", "3e-4, 5", "1e-4, 10", "1e-4, 5"]);
    expect(rows[0]?.querySelector("text")?.getAttribute("class")).toBe("lbl-b");
    expect(rows[1]?.querySelector("text")?.getAttribute("class")).toBe("lbl");
    expect(screen.getByText("lr, beam")).toBeTruthy();
    expect(screen.getByText("top1 v1")).toBeTruthy();
  });

  test("seed dots, means, whiskers, the best band and n= for short cells", () => {
    const { container } = renderForest();
    expect(container.querySelectorAll("circle.seed")).toHaveLength(5);
    expect(container.querySelectorAll("rect.mean")).toHaveLength(4);
    expect(container.querySelectorAll("rect.mean.best")).toHaveLength(1);
    expect(container.querySelectorAll("path.whisk")).toHaveLength(4);
    expect(container.querySelectorAll("g.best-band")).toHaveLength(1);
    expect(screen.getAllByText("n=1")).toHaveLength(3);
  });

  test("identical seeds collapse to one diamond with ×n, never stacked dots", () => {
    const { container } = renderForest({ seedsOf: (c) => (c.n === 2 ? [0.912, 0.912] : seedValues(c, BOARD)) });
    const best = container.querySelector('g.frow[data-label="3e-4, 10"]') as Element;
    expect(best.querySelectorAll("circle.seed")).toHaveLength(0);
    expect(best.querySelector("g.identical path.dia")).toBeTruthy();
    expect(best.querySelector("g.identical text")?.textContent).toBe("×2");
    // the other rows keep their dots
    expect(container.querySelectorAll("circle.seed")).toHaveLength(3);
  });

  test("hovering a row shows the cell's numbers", () => {
    const { container } = renderForest();
    fireEvent.mouseEnter(container.querySelector("g.frow rect.hit") as Element);
    expect(screen.getByRole("tooltip").textContent).toBe(
      cellTip(parseCell(CELL_D) as SweepCellRow, NAMES, [0.911, 0.913]),
    );
  });

  test("no scored cell: a short note instead of a chart", () => {
    const { container } = renderForest({
      cells: parseCells([{ params: { lr: "1e-4", beam: "5" }, run_ids: ["x"] }]),
      best: null,
    });
    expect(screen.getByText("No scored runs yet")).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
  });
});
