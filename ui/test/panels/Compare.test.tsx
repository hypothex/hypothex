import { expect, test } from "bun:test";
import { render, screen, within } from "@testing-library/react";
import { PANELS } from "../../src/panels";
import { ComparePanelResult } from "../../src/panels/Compare";

const rows = [
  { dataset: "test-a", model: "model-x", metric: "top10", key: "reported/test-a.model-x.top10", run_id: "run-v1", group_id: "g-v1", name: "db v1", value: 0.7 },
  { dataset: "test-b", model: "model-x", metric: "top10", key: "reported/test-b.model-x.top10", run_id: "run-v1", group_id: "g-v1", name: "db v1", value: 0.65 },
  { dataset: "test-a", model: "model-x", metric: "top10", key: "reported/test-a.model-x.top10", run_id: "run-v3", group_id: "g-v3", name: "db v3", value: 0.9 },
];

test("the registry draws a saved compare panel from its rows", () => {
  expect(PANELS.compare).toBe(ComparePanelResult);
  render(<ComparePanelResult result={{ type: "compare", title: "Compare", rows, meta: {} }} />);
  const table = screen.getByRole("table", { name: "Compare table" });
  expect(within(table).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["test-a", "test-b"]);
  expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["top10 · dataset", "db v1", "db v3"]);
  expect(within(table).getAllByRole("cell").map((c) => c.textContent)).toEqual(["0.7000", "0.9000", "0.6500", "—"]);
});

test("render: bars from the view; no rows says so", () => {
  const { container, unmount } = render(<ComparePanelResult result={{ type: "compare", title: "Compare", rows, meta: { render: "bars" } }} />);
  expect(container.querySelector(".facet-h")?.textContent).toBe("top10");
  unmount();
  render(<ComparePanelResult result={{ type: "compare", title: "Compare", rows: [], meta: {} }} />);
  expect(screen.getByText("No compare rows")).toBeTruthy();
});

test("control labels come from the view's key parts; the direction from meta", () => {
  render(<ComparePanelResult result={{ type: "compare", title: "Compare", rows, meta: { key_parts: ["split", "arch", "metric"], higher_is_better: false } }} />);
  expect(screen.getByRole("group", { name: "Splits" })).toBeTruthy();
  const first = within(screen.getByRole("table", { name: "Compare table" })).getAllByRole("row")[1] as HTMLElement;
  expect(within(first).getAllByRole("cell").map((c) => [c.textContent, c.className.includes("best")])).toEqual([
    ["0.7000", true],
    ["0.9000", false],
  ]);
});

test("each row's best follows that row's own direction; meta only for rows without one", () => {
  const directed = [
    { ...rows[0], higher_is_better: false },
    { ...rows[1], higher_is_better: true },
    { ...rows[2], higher_is_better: false },
    { ...rows[1], run_id: "run-v3", group_id: "g-v3", name: "db v3", value: 0.95, higher_is_better: true },
  ];
  render(<ComparePanelResult result={{ type: "compare", title: "Compare", rows: directed, meta: { higher_is_better: false } }} />);
  const table = screen.getByRole("table", { name: "Compare table" });
  const marked = within(table).getAllByRole("cell").filter((c) => c.className.includes("best")).map((c) => c.textContent);
  expect(marked).toEqual(["0.7000", "0.9500"]);
});
