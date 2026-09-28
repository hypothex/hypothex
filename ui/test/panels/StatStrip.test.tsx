import { afterEach, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { StatStrip, fmtStat } from "../../src/panels/StatStrip";
import type { PanelResult } from "../../src/panels/index";

afterEach(cleanup);

const result: PanelResult = {
  type: "stat_strip",
  title: "SVM vs rf",
  rows: [
    { label: "Δ accuracy", value: 0.037, unit: null, tooltip: "0.0370 = 6.7 of 180 examples" },
    { label: "paired p", value: "0.15", unit: null, tooltip: "Exact two-sided sign test" },
    { label: "fixed / broken", value: "9 / 3", unit: null, tooltip: null },
    { label: "seed σ", value: 0.0064, unit: null, tooltip: null },
    { label: "n for p < 0.05", value: 250, unit: "examples", tooltip: null },
    { label: "cost", value: null, unit: "$", tooltip: null },
  ],
  meta: { headline: "SVM +0.037 over rf, p = 0.15" },
};

test("fmtStat formats numbers, keeps strings, dashes missing values", () => {
  expect(fmtStat(0.037)).toBe("0.037");
  expect(fmtStat(40000)).toBe("40,000");
  expect(fmtStat("9 / 3")).toBe("9 / 3");
  expect(fmtStat(null)).toBe("—");
  expect(fmtStat("")).toBe("—");
});

test("renders one labelled number per row with tooltip and unit", () => {
  const { container } = render(<StatStrip result={result} />);
  const items = [...container.querySelectorAll("dl.stats > div")];
  expect(items.length).toBe(6);
  expect(items.map((d) => d.querySelector("dt")?.textContent)).toEqual([
    "Δ accuracy",
    "paired p",
    "fixed / broken",
    "seed σ",
    "n for p < 0.05",
    "cost",
  ]);
  expect(items.map((d) => d.querySelector("dd")?.textContent)).toEqual([
    "0.037",
    "0.15",
    "9 / 3",
    "0.0064",
    "250 examples",
    "— $",
  ]);
  expect(items[0]?.getAttribute("title")).toBe("0.0370 = 6.7 of 180 examples");
  expect(items[2]?.hasAttribute("title")).toBe(false);
  expect(screen.queryByText("SVM +0.037 over rf, p = 0.15")).toBeNull();
});

test("skips malformed rows and shows an empty state when nothing is left", () => {
  const { container } = render(
    <StatStrip result={{ type: "stat_strip", title: "", rows: [{ value: 1 }, { label: 3 }] }} />,
  );
  expect(container.querySelector("dl")).toBeNull();
  expect(screen.getByText("No stats yet")).toBeTruthy();
});
