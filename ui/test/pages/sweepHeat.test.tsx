import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, screen, within } from "@testing-library/react";
import type { RunStatus } from "../../src/api/models";
import { SweepHeat, type SweepHeatProps } from "../../src/pages/components/SweepHeat";
import {
  type HeatAxes,
  type SweepCellRow,
  cellTip,
  heatAxes,
  parseCell,
  parseCells,
  runState,
  seedValues,
} from "../../src/pages/components/SweepModel";
import { renderWithClient } from "./helpers";
import { CELL_A, CELL_B, CELL_D, RAW_CELLS, RUNS, STALE, makeSummary, makeSweepBoard, rid } from "./sweepFixtures";

afterEach(cleanup);

const AXES = heatAxes(makeSummary().spec) as HeatAxes;
const BOARD = makeSweepBoard();
const BY_ID = new Map(RUNS.map((r) => [r.run_id, r]));
const stateOf = (id: string, fallback: RunStatus | null) => runState(BY_ID.get(id), fallback, STALE);

function renderHeat(over: Partial<SweepHeatProps> = {}) {
  return renderWithClient(
    <SweepHeat
      axes={AXES}
      cells={parseCells(RAW_CELLS)}
      best={parseCell(CELL_D)}
      metric="top1"
      higherIsBetter
      maxSeeds={2}
      stateOf={stateOf}
      seedsOf={(c) => seedValues(c, BOARD)}
      {...over}
    />,
  );
}

const cell = (key: string): HTMLElement => screen.getByTestId(`cell-${key}`);
const texts = (els: Iterable<Element>): (string | null)[] => [...els].map((e) => e.textContent);

describe("SweepHeat", () => {
  test("rows and columns are the two params, with row and column means", () => {
    const { container } = renderHeat();
    const table = screen.getByRole("table", { name: "Mean top1 by lr and beam" });
    expect(texts(within(table).getAllByRole("columnheader"))).toEqual(["lr \\ beam", "5", "10", "mean"]);
    expect(texts(within(table).getAllByRole("rowheader"))).toEqual(["1e-4", "3e-4", "mean"]);
    expect(texts(container.querySelectorAll("td.m.rm"))).toEqual(["0.8950", "0.9080"]);
    expect(texts(container.querySelectorAll("td.m:not(.rm)"))).toEqual(["0.8970", "0.9060"]);
  });

  test("each cell shows its mean, n when seeds are missing, the best mark and its heat", () => {
    renderHeat();
    const best = cell("3e-4|10");
    expect(best.className).toBe("c best");
    expect(within(best).getByText("◆ best")).toBeTruthy();
    expect(best.querySelector(".v")?.textContent).toBe("0.9120");
    expect(best.getAttribute("data-heat")).toBe("34");
    expect(best.querySelector(".v")?.getAttribute("title")).toBe(
      cellTip(parseCell(CELL_D) as SweepCellRow, ["lr", "beam"], [0.911, 0.913]),
    );
    const low = cell("1e-4|5");
    expect(low.className).toBe("c");
    expect(low.querySelector(".v")?.textContent).toBe("0.8900n=1");
    expect(low.getAttribute("data-heat")).toBe("4");
  });

  test("each cell links its runs with a state glyph; a running run on a stale host is stale", () => {
    renderHeat();
    const glyph = (key: string, tail: string): string | null | undefined =>
      within(cell(key)).getByRole("link", { name: tail }).querySelector("svg")?.getAttribute("data-glyph");
    expect(within(cell("3e-4|10")).getByRole("link", { name: "d1" }).getAttribute("href")).toBe(`/r/${rid("d1")}`);
    expect([glyph("1e-4|5", "a1"), glyph("1e-4|5", "a2"), glyph("1e-4|10", "b2"), glyph("3e-4|5", "c2")]).toEqual([
      "finished",
      "queued",
      "stale",
      "failed",
    ]);
  });

  test("the key shows the value range, the best cell's seeds and the glyphs in use", () => {
    renderHeat();
    const key = screen.getByLabelText("Key");
    expect(within(key).getByText("0.890–0.912")).toBeTruthy();
    expect(within(key).getByText("best, 2 seeds")).toBeTruthy();
    expect(texts(key.querySelectorAll("span.st-k"))).toEqual(["finished", "running", "queued", "failed", "stale"]);
  });

  test("a missing combination is an empty cell; long run lists are cut", () => {
    const many = {
      ...CELL_A,
      run_ids: [],
      runs: Array.from({ length: 8 }, (_, i) => ({ run_id: rid(`m${i}`), status: "queued", seed: i + 1 })),
    };
    renderHeat({ cells: parseCells([many, CELL_B, CELL_D]) });
    const empty = cell("3e-4|5");
    expect(empty.className).toBe("c empty");
    expect(empty.querySelector(".v")?.textContent).toBe("·");
    expect(empty.getAttribute("data-heat")).toBeNull();
    expect(within(cell("1e-4|5")).getAllByRole("link")).toHaveLength(6);
    expect(within(cell("1e-4|5")).getByText("+2")).toBeTruthy();
  });

  test("for a lower-is-better metric the lowest mean is darkest", () => {
    renderHeat({ higherIsBetter: false, best: parseCell(CELL_A) });
    expect(cell("1e-4|5").getAttribute("data-heat")).toBe("34");
    expect(cell("3e-4|10").getAttribute("data-heat")).toBe("4");
    expect(cell("1e-4|5").className).toBe("c best");
  });
});

test("heat cell separates scored and uncounted members even when all expected seeds are present", () => {
  const row = parseCell({ ...CELL_D, n: 3, uncounted: 2 })!;
  renderHeat({ cells: [row], best: row, maxSeeds: 3 });
  expect(screen.getByText("n=3 +2")).toBeTruthy();
  expect(cell("3e-4|10").querySelector(".v")?.getAttribute("title")).toContain("2 uncounted runs");
});
