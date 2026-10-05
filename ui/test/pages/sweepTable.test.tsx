import { afterEach, describe, expect, spyOn, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { parseCell, parseCells } from "../../src/pages/components/SweepModel";
import { SweepTable, type SweepTableProps } from "../../src/pages/components/SweepTable";
import { renderWithClient } from "./helpers";

afterEach(cleanup);

function raw(id: string, lr: string, beam: string, warmup: string, n: number, mean: number | null): unknown {
  return {
    params: { lr, beam, warmup },
    group_id: n > 0 ? `g-${id}` : null,
    n,
    mean,
    lo: mean === null ? null : mean - 0.02,
    hi: mean === null ? null : mean + 0.02,
    std: null,
    run_ids: [`20261003-${id}`],
    runs: [{ run_id: `20261003-${id}`, status: mean === null ? "queued" : "finished", seed: 1 }],
  };
}

const CELLS = [
  raw("t1", "1e-4", "5", "100", 2, 0.8),
  raw("t2", "3e-4", "5", "100", 2, 0.85),
  raw("t3", "1e-3", "10", "0", 0, null),
  raw("t4", "3e-5", "10", "0", 1, 0.82),
];

function renderTable(over: Partial<SweepTableProps> = {}) {
  return renderWithClient(
    <SweepTable
      names={["lr", "beam", "warmup"]}
      cells={parseCells(CELLS)}
      best={parseCell(CELLS[1])}
      metric="top1"
      higherIsBetter
      maxSeeds={2}
      stateOf={(_id, fallback) => fallback ?? "queued"}
      {...over}
    />,
  );
}

const firstColumn = (): (string | null)[] =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelector("td")?.textContent ?? null);
const header = (name: RegExp): HTMLElement => screen.getByRole("button", { name }).closest("th") as HTMLElement;

describe("SweepTable", () => {
  test("sorts by mean, best first, and marks the best row", () => {
    renderTable();
    expect(screen.getByRole("table", { name: "Mean top1 by lr, beam, warmup" })).toBeTruthy();
    expect(firstColumn()).toEqual(["3e-4", "3e-5", "1e-4", "1e-3"]);
    expect(header(/^top1/).getAttribute("aria-sort")).toBe("descending");
    const bestRow = screen.getAllByRole("row")[1] as HTMLElement;
    expect(bestRow.className).toBe("best");
    expect(bestRow.textContent).toContain("◆");
  });

  test("a param header sorts numerically, a second click reverses", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: /^lr/ }));
    expect(firstColumn()).toEqual(["3e-5", "1e-4", "3e-4", "1e-3"]);
    expect(header(/^lr/).getAttribute("aria-sort")).toBe("ascending");
    expect(header(/^top1/).getAttribute("aria-sort")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^lr/ }));
    expect(firstColumn()).toEqual(["1e-3", "3e-4", "1e-4", "3e-5"]);
    expect(header(/^lr/).getAttribute("aria-sort")).toBe("descending");
  });

  test("the n header sorts by scored seeds", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: /^n\b/ }));
    expect(firstColumn()).toEqual(["1e-3", "3e-5", "1e-4", "3e-4"]);
  });

  test("a lower-is-better metric sorts ascending by default", () => {
    renderTable({ higherIsBetter: false, best: parseCell(CELLS[0]) });
    expect(firstColumn()).toEqual(["1e-4", "3e-5", "3e-4", "1e-3"]);
    expect(header(/^top1/).getAttribute("aria-sort")).toBe("ascending");
  });

  test("lower-is-better arriving after the first render still sorts best first; a click then sticks", () => {
    // the sweep page renders before the leaderboard says the metric's direction
    const props: SweepTableProps = {
      names: ["lr", "beam", "warmup"],
      cells: parseCells(CELLS),
      best: parseCell(CELLS[1]),
      metric: "top1",
      higherIsBetter: true,
      maxSeeds: 2,
      stateOf: (_id, fallback) => fallback ?? "queued",
    };
    const { rerender } = render(<SweepTable {...props} />);
    expect(firstColumn()).toEqual(["3e-4", "3e-5", "1e-4", "1e-3"]);
    rerender(<SweepTable {...props} higherIsBetter={false} best={parseCell(CELLS[0])} />);
    expect(firstColumn()).toEqual(["1e-4", "3e-5", "3e-4", "1e-3"]);
    expect(header(/^top1/).getAttribute("aria-sort")).toBe("ascending");
    // once the user picks a column, a later prop change keeps that choice
    fireEvent.click(screen.getByRole("button", { name: /^lr/ }));
    rerender(<SweepTable {...props} higherIsBetter />);
    expect(firstColumn()).toEqual(["3e-5", "1e-4", "3e-4", "1e-3"]);
  });

  test("params named n and mean keep their own sort keys apart from the built-in columns", () => {
    const cell = (n: string, mean: string, scored: number, score: number): unknown => ({
      params: { n, mean },
      group_id: `g-${n}-${mean}`,
      n: scored,
      mean: score,
      lo: null,
      hi: null,
      std: null,
      run_ids: [],
      runs: [],
    });
    const raws = [cell("3", "b", 1, 0.5), cell("1", "c", 3, 0.9), cell("2", "a", 2, 0.7)];
    const errors = spyOn(console, "error").mockImplementation(() => {});
    try {
      renderTable({ names: ["n", "mean"], cells: parseCells(raws), best: parseCell(raws[1]), maxSeeds: 3 });
      // React warns on duplicate <th> keys; there must be none
      expect(errors.mock.calls.map((c) => String(c[0])).filter((m) => m.includes("same key"))).toEqual([]);
    } finally {
      errors.mockRestore();
    }
    const heads = (): HTMLElement[] => [...document.querySelectorAll("thead th")] as HTMLElement[];
    const click = (i: number): void => {
      fireEvent.click(heads()[i]?.querySelector("button") as HTMLElement);
    };
    const sorted = (): (string | null)[] => heads().map((th) => th.getAttribute("aria-sort"));
    // columns: param n, param mean, built-in n, top1, CI, runs
    expect(firstColumn()).toEqual(["1", "2", "3"]);
    expect(sorted()).toEqual([null, null, null, "descending", null, null]);
    click(0);
    expect(firstColumn()).toEqual(["1", "2", "3"]);
    expect(sorted()).toEqual(["ascending", null, null, null, null, null]);
    click(1);
    expect(firstColumn()).toEqual(["2", "3", "1"]);
    expect(sorted()).toEqual([null, "ascending", null, null, null, null]);
    click(2);
    expect(firstColumn()).toEqual(["3", "2", "1"]);
    expect(sorted()).toEqual([null, null, "ascending", null, null, null]);
  });

  test("an unscored cell shows dashes and its queued run", () => {
    renderTable();
    const row = screen.getAllByRole("row")[4] as HTMLElement;
    expect([...row.querySelectorAll("td")].map((td) => td.textContent)).toEqual([
      "1e-3",
      "10",
      "0",
      "0",
      "—",
      "—",
      "t3",
    ]);
    expect(row.querySelector("svg")?.getAttribute("data-glyph")).toBe("queued");
  });
});

test("table shows uncounted separately without changing n or the score", () => {
  const row = parseCell({ params: { lr: "0.1" }, n: 3, uncounted: 2, mean: 0.8 })!;
  renderTable({ cells: [row], best: null });
  expect(screen.getByText("3 +2").title).toBe("3 scored, 2 uncounted");
  expect(screen.getByText("0.8000")).toBeTruthy();
});
