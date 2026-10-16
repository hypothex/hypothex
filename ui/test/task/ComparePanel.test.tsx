import { describe, expect, test } from "bun:test";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { ComparePanel } from "../../src/task/ComparePanel";
import { type CompareState, compareModel, defaultCompare } from "../../src/task/compareModel";
import { listIdentities, parseSelection } from "../../src/task/useRunSelection";
import { EVAL_PRIMARY, makeEvalTaskRuns } from "./fixtures";

const data = makeEvalTaskRuns();
const built = compareModel(data.score_keys, EVAL_PRIMARY, data.key_parts);
if (!built) throw new Error("fixture has no compare model");
const model = built;
const items = listIdentities(parseSelection(new URLSearchParams(), { sortDir: "desc" }), data);
const columns = items.map((i, n) => ({ id: i.id, name: i.name, color: `var(--c${n + 1})`, scores: i.group?.scores ?? {} }));

function Harness({ initial }: { initial: CompareState }) {
  const [state, setState] = useState(initial);
  return <ComparePanel model={model} state={state} onState={setState} columns={columns} higherIsBetter={() => true} />;
}
const start = () => render(<Harness initial={defaultCompare(model, EVAL_PRIMARY, data.key_parts)} />);
const panelOf = () => screen.getByRole("region", { name: /^Compare datasets/ });

describe("ComparePanel", () => {
  test("table by default: a row per dataset, a column per run, best value marked", () => {
    start();
    const panel = panelOf();
    expect(panel.getAttribute("aria-label")).toBe("Compare datasets · model-x");
    const table = within(panel).getByRole("table", { name: "Compare table" });
    expect(within(table).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["test-a", "test-b", "test-c", "test-d"]);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["top10 · dataset", "db v3", "db v2", "db v1"]);
    const first = within(table).getAllByRole("row")[1] as HTMLElement;
    expect(within(first).getAllByRole("cell").map((c) => [c.textContent, c.className.includes("best")])).toEqual([
      ["0.9000", true],
      ["0.8000", false],
      ["0.7000", false],
    ]);
    expect(within(panel).getByText("4 × 3 runs")).toBeTruthy();
  });

  test("chips: add a dataset, the last one stays, switch the model, add a metric", () => {
    start();
    const panel = panelOf();
    const datasets = within(panel).getByRole("group", { name: "Datasets" });
    fireEvent.click(within(datasets).getByRole("checkbox", { name: "test-e" }));
    const table = () => within(panel).getByRole("table", { name: "Compare table" });
    expect(within(table()).getAllByRole("rowheader")).toHaveLength(5);
    for (const d of ["test-a", "test-b", "test-c", "test-d", "test-e"]) fireEvent.click(within(datasets).getByRole("checkbox", { name: d }));
    expect(within(table()).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["test-e"]);
    expect(within(datasets).getByRole("checkbox", { name: "test-e" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(within(panel).getByRole("radiogroup", { name: "Model" })).getByRole("radio", { name: "model-y" }));
    expect(panel.getAttribute("aria-label")).toBe("Compare datasets · model-y");
    fireEvent.click(within(within(panel).getByRole("group", { name: "Metrics" })).getByRole("checkbox", { name: "top1" }));
    expect([...table().querySelectorAll("tr.g")].map((r) => r.textContent)).toEqual(["top1", "top10"]);
    expect(within(table()).getAllByRole("columnheader")[0]?.textContent).toBe("Metric · dataset");
    const top1 = within(table()).getAllByRole("row")[2] as HTMLElement;
    expect(within(top1).getAllByRole("cell").map((c) => c.textContent)).toEqual(["0.3700", "0.2700", "—"]);
  });

  test("Bars: grouped bars per metric with a legend; Table switches back", () => {
    start();
    const panel = panelOf();
    fireEvent.click(within(panel).getByRole("button", { name: "Bars" }));
    expect(within(panel).queryByRole("table")).toBeNull();
    expect(panel.querySelector(".legend")?.textContent).toBe("db v3db v2db v1");
    expect([...panel.querySelectorAll(".facet-h")].map((e) => e.textContent)).toEqual(["top10"]);
    fireEvent.click(within(panel).getByRole("button", { name: "Table" }));
    expect(within(panel).getByRole("table", { name: "Compare table" })).toBeTruthy();
  });

});
