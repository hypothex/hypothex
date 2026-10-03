import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { MINUS } from "../../src/charts/Scale";
import { fmtNum, fmtSigned } from "../../src/charts/valueFormat";
import {
  columnLabel,
  fmtCell,
  panelColumns,
  ROW_CAP,
  sortRows,
  TablePanel,
  visibleColumns,
  tableColumns,
} from "../../src/panels/Table";

afterEach(cleanup);

const table = (rows: Record<string, unknown>[]): PanelResult => ({
  type: "table",
  title: "Runs",
  rows,
  meta: {},
});

const bodyCells = (container: HTMLElement, col: number): string[] =>
  [...container.querySelectorAll("tbody tr")].map(
    (tr) => tr.querySelectorAll("td")[col]?.textContent ?? "",
  );

describe("fmtNum", () => {
  test("metric values in [0, 1] get three decimals", () => {
    expect(fmtNum(0.6634)).toBe("0.663");
    expect(fmtNum(0.5)).toBe("0.500");
  });

  test("integers are grouped; other values get three significant digits", () => {
    expect(fmtNum(200)).toBe("200");
    expect(fmtNum(12000)).toBe("12,000");
    expect(fmtNum(12.345)).toBe("12.3");
    expect(fmtNum(1234.5)).toBe("1,235");
  });

  test("negatives use a true minus; tiny values keep two significant digits", () => {
    expect(fmtNum(-0.25)).toBe("−0.250");
    expect(fmtNum(0.00012345)).toBe("0.00012");
    expect(fmtNum(Number.NaN)).toBe("NaN");
  });
});

describe("fmtCell", () => {
  test("formats each JSON type", () => {
    expect(fmtCell(null)).toBe("—");
    expect(fmtCell(undefined)).toBe("—");
    expect(fmtCell(true)).toBe("✓");
    expect(fmtCell(false)).toBe("✗");
    expect(fmtCell("finished")).toBe("finished");
    expect(fmtCell({ a: 1 })).toBe('{"a":1}');
    expect(fmtCell(0.9)).toBe("0.900");
  });
});

describe("tableColumns and sortRows", () => {
  test("columns are the union of keys in first-seen order", () => {
    expect(
      tableColumns([
        { run_id: "r1", acc: 0.9 },
        { run_id: "r2", loss: 1.5 },
      ]),
    ).toEqual(["run_id", "acc", "loss"]);
  });

  test("missing values sort last in both directions", () => {
    const rows = [{ acc: 0.9 }, { acc: null }, { acc: 0.7 }, { acc: 0.8 }];
    expect(sortRows(rows, "acc", "asc").map((r) => r.acc)).toEqual([0.7, 0.8, 0.9, null]);
    expect(sortRows(rows, "acc", "desc").map((r) => r.acc)).toEqual([0.9, 0.8, 0.7, null]);
  });

  test("strings sort with numeric awareness", () => {
    const rows = [{ id: "r10" }, { id: "r2" }, { id: "r1" }];
    expect(sortRows(rows, "id", "asc").map((r) => r.id)).toEqual(["r1", "r2", "r10"]);
  });
});

describe("TablePanel", () => {
  const rows = [
    { run_id: "r1", status: "finished", acc: 0.9 },
    { run_id: "r2", status: "failed", acc: null },
    { run_id: "r3", status: "finished", acc: 0.7 },
  ];

  test("renders headers, formatted cells and run links", () => {
    const { container } = render(<TablePanel result={table(rows)} />);
    expect(screen.getByRole("button", { name: "acc" })).toBeTruthy();
    expect(bodyCells(container, 2)).toEqual(["0.900", "—", "0.700"]);
    expect(screen.getByRole("link", { name: "r1" }).getAttribute("href")).toBe("/r/r1");
  });

  test("header clicks cycle ascending, descending, original order", () => {
    const { container } = render(<TablePanel result={table(rows)} />);
    const btn = screen.getByRole("button", { name: "acc" });
    fireEvent.click(btn);
    expect(bodyCells(container, 2)).toEqual(["0.700", "0.900", "—"]);
    expect(btn.closest("th")?.getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(btn);
    expect(bodyCells(container, 2)).toEqual(["0.900", "0.700", "—"]);
    expect(btn.closest("th")?.getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(btn);
    expect(bodyCells(container, 0)).toEqual(["r1", "r2", "r3"]);
    expect(btn.closest("th")?.getAttribute("aria-sort")).toBe("none");
  });

  test("caps rendered rows and says how many exist", () => {
    const many = Array.from({ length: ROW_CAP + 1 }, (_, i) => ({ i }));
    const { container } = render(<TablePanel result={table(many)} />);
    expect(container.querySelectorAll("tbody tr").length).toBe(ROW_CAP);
    expect(screen.getByText("500 of 501 rows")).toBeTruthy();
  });

  test("meta.columns (the view's fields) are the only columns drawn", () => {
    const rows = [
      { run_id: "r1", group_id: "g", label: "svm", seed: 1, turn: 1, tokens_in: 90, tokens_out: 12, seconds: 0.4 },
    ];
    const columns = ["turn", "tokens_in", "tokens_out", "seconds"];
    expect(panelColumns(rows, { columns })).toEqual(columns);
    expect(panelColumns(rows, {})).toEqual(["run_id", "label", "seed", ...columns]);
    render(<TablePanel result={{ ...table(rows), meta: { columns } }} />);
    const heads = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toHaveLength(4);
    expect(heads.some((h) => /run|label|seed/.test(h ?? ""))).toBe(false);
  });

  test("empty result says so", () => {
    render(<TablePanel result={table([])} />);
    expect(screen.getByText("No rows")).toBeTruthy();
  });
});

test("a missing value in a numeric column is right-aligned with the numbers", () => {
  const rows = [{ v: "v1", d: null }, { v: "v2", d: 0.025 }];
  const { container } = render(<TablePanel result={{ type: "table", title: "t", rows, meta: {} }} />);
  const cells = [...container.querySelectorAll("tbody tr")].map((tr) => tr.querySelectorAll("td")[1] as HTMLElement);
  expect(cells.map((td) => [td.textContent, td.style.textAlign])).toEqual([
    ["—", "right"],
    ["0.025", "right"],
  ]);
});

test("headers are short names with the field as tooltip; deltas are signed; run ids short", () => {
  expect(columnLabel("run_id")).toBe("run");
  expect(columnLabel("delta_prev")).toBe("Δ prev");
  expect(columnLabel("usage.tokens_in")).toBe("tokens in");
  expect(columnLabel("meta.category")).toBe("category");
  expect(columnLabel("usage.seconds")).toBe("time");
  expect(fmtSigned(0.025)).toBe("+0.025");
  expect(fmtSigned(-0.048)).toBe(`${MINUS}0.048`);
  expect(fmtSigned(0)).toBe("0");
  const rows = [
    { run_id: "20260927-110306-toy-test-4093", delta_prev: 0.025 },
    { run_id: "20260927-110304-toy-test-d45c", delta_prev: -0.048 },
  ];
  const { container } = render(<TablePanel result={{ type: "table", title: "t", rows, meta: {} }} />);
  const head = screen.getByRole("button", { name: "Δ prev" });
  expect(head.getAttribute("title")).toBe("delta_prev");
  expect(bodyCells(container, 1)).toEqual(["+0.025", `${MINUS}0.048`]);
  const link = screen.getByRole("link", { name: "4093" });
  expect(link.getAttribute("href")).toBe("/r/20260927-110306-toy-test-4093");
  expect(link.closest("td")?.getAttribute("title")).toBe("20260927-110306-toy-test-4093");
});

test("group_id folds into the label column, whose tooltip keeps the id", () => {
  expect(visibleColumns(["run_id", "group_id", "label", "seed"])).toEqual(["run_id", "label", "seed"]);
  expect(visibleColumns(["run_id", "group_id"])).toEqual(["run_id", "group_id"]);
  const rows = [{ run_id: "r1", group_id: "9b8c87bd@3d9e1a7", label: "base recipe", seed: 1 }];
  const { container } = render(<TablePanel result={{ type: "table", title: "t", rows, meta: {} }} />);
  expect([...container.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["run", "label", "seed"]);
  const cell = container.querySelectorAll("tbody td")[1];
  expect(cell?.getAttribute("title")).toBe("base recipe\n9b8c87bd@3d9e1a7");
});
