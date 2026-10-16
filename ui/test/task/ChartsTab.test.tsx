import { afterEach, describe, expect, test } from "bun:test";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ViewQueryBody } from "../../src/api/models";
import { ChartsTab, type ChartsTabProps } from "../../src/task/ChartsTab";
import { parseSelection } from "../../src/task/useRunSelection";
import { type Call, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { BASE, PROJECT, TASK, makeEvalTaskRuns, makeTaskRuns, presetDoc } from "./fixtures";

afterEach(restoreFetch);

const CURVES = [
  { run_id: "run-a1", group_id: "g-a", seed: 1, name: "train/loss", step: 0, value: 2.1 },
  { run_id: "run-a1", group_id: "g-a", seed: 1, name: "train/loss", step: 100, value: 1.2 },
];
function query(c: Call) {
  const body = c.body as ViewQueryBody;
  if (body.view?.title === "Step metrics") return { panels: [{ type: "curves", title: "step metrics 1", rows: CURVES, meta: {} }] };
  return { panels: (body.view?.panels ?? []).map((p) => ({ type: p.type, title: p.title ?? p.type, rows: [], meta: {} })) };
}
const ROUTES = {
  [`GET ${BASE}/views/overview`]: presetDoc("training"),
  [`POST ${BASE}/views/query`]: query,
  [`GET /api/v1/runs?project=${PROJECT}&task=${TASK}&limit=21`]: [],
  [`GET ${BASE}`]: { summary: { metrics: {} } },
};
const stepBodies = (calls: Call[]) =>
  calls.map((c) => c.body as ViewQueryBody | undefined).filter((b): b is ViewQueryBody => b?.view?.title === "Step metrics");
const sel = parseSelection(new URLSearchParams(), { sortDir: "desc" });
const registry = fakeRegistry(["stat_strip", "table", "curves"]);
const charts = (over: Partial<ChartsTabProps> = {}) => (
  <ChartsTab
    project={PROJECT}
    task={TASK}
    data={makeTaskRuns()}
    board={undefined}
    selection={sel}
    onSelection={() => {}}
    onOpenRun={() => {}}
    onOpenView={() => {}}
    viewNames={[]}
    {...over}
  />
);

describe("ChartsTab", () => {
  test("toolbar: panel search, smoothing with its value, x axis without time, seeds", () => {
    mockApi(ROUTES);
    renderWithClient(charts(), { registry });
    expect(screen.getByRole("searchbox", { name: "Search panels" })).toBeTruthy();
    const slider = screen.getByRole("slider", { name: "Smoothing" }) as HTMLInputElement;
    expect(slider.value).toBe("0.6");
    expect(screen.getByText("0.60")).toBeTruthy();
    fireEvent.change(slider, { target: { value: "0.35" } });
    expect(screen.getByText("0.35")).toBeTruthy();
    const x = screen.getByRole("combobox", { name: "X axis" });
    expect(within(x).getAllByRole("option").map((o) => [(o as HTMLOptionElement).value, (o as HTMLOptionElement).disabled])).toEqual([
      ["step", false],
      ["wall", true],
      ["relative", true],
    ]);
    expect(within(screen.getByRole("combobox", { name: "Seeds" })).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "mean",
      "mean + band",
      "each seed",
    ]);
  });

  test("x axis offers wall and relative time once a curve row carries t", async () => {
    mockApi({
      ...ROUTES,
      [`POST ${BASE}/views/query`]: (c: Call) =>
        (c.body as ViewQueryBody).view?.title === "Step metrics"
          ? { panels: [{ type: "curves", title: "step metrics 1", rows: CURVES.map((r, i) => ({ ...r, t: 1000 + i })), meta: {} }] }
          : query(c),
    });
    renderWithClient(charts(), { registry });
    const x = screen.getByRole("combobox", { name: "X axis" });
    await waitFor(() => expect((within(x).getByRole("option", { name: "wall time" }) as HTMLOptionElement).disabled).toBe(false));
  });

  test("a task without step metrics has no step-metric controls; sweep/* and step are not step metrics", async () => {
    const calls = mockApi(ROUTES);
    renderWithClient(charts({ data: makeTaskRuns({ metric_names: ["sweep/lr", "step"] }) }), { registry });
    expect(screen.getByRole("searchbox", { name: "Search panels" })).toBeTruthy();
    expect(screen.queryByRole("slider", { name: "Smoothing" })).toBeNull();
    await screen.findByRole("region", { name: "Summary" });
    expect(stepBodies(calls)).toHaveLength(0);
  });

  test("system benchmarks call seeds repeats", () => {
    mockApi({ ...ROUTES, [`GET ${BASE}/views/overview`]: presetDoc("system_bench") });
    renderWithClient(charts({ data: makeTaskRuns({ kind: "system_bench" }) }), { registry });
    expect(within(screen.getByRole("combobox", { name: "Repeats" })).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "mean",
      "mean + band",
      "each repeat",
    ]);
  });

  test("step metrics: one query for the visible runs, a section per prefix, a panel per metric", async () => {
    const calls = mockApi(ROUTES);
    renderWithClient(charts(), { registry });
    await waitFor(() => expect(stepBodies(calls)).toHaveLength(1));
    expect(stepBodies(calls)[0]?.view?.panels?.[0]?.data).toEqual({
      metrics: ["train/loss", "val/loss", "val/top1", "sys/gpu_util"],
      group_by: "group",
      max_points: 300,
      filter: { run_id: ["run-a1", "run-a2", "run-a3", "run-b1", "run-b2", "run-c1", "run-c2"] },
    });
    for (const [section, panels] of [["train", ["train/loss"]], ["val", ["val/loss", "val/top1"]], ["sys", ["sys/gpu_util"]]] as const) {
      const region = screen.getByRole("region", { name: section });
      for (const p of panels) expect(within(region).getByRole("region", { name: p })).toBeTruthy();
    }
    const scores = screen.getByRole("region", { name: "Scores" });
    expect(within(scores).getByRole("region", { name: "top1" })).toBeTruthy();
    expect(within(scores).getByRole("region", { name: "top1 vs GPU-hours" })).toBeTruthy();
  });

  test("hidden configs leave the query; the panel search hides panels and empty sections", async () => {
    const calls = mockApi(ROUTES);
    renderWithClient(charts({ selection: { ...sel, hidden: ["g-b"] } }), { registry });
    await waitFor(() => expect(stepBodies(calls)).toHaveLength(1));
    expect(stepBodies(calls)[0]?.view?.panels?.[0]?.data?.filter).toEqual({ run_id: ["run-a1", "run-a2", "run-a3", "run-c1", "run-c2"] });
    await screen.findByRole("region", { name: "Summary" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search panels" }), { target: { value: "loss" } });
    expect(screen.getByRole("region", { name: "train/loss" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "val/top1" })).toBeNull();
    expect(screen.queryByRole("region", { name: "sys" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Scores" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Summary" })).toBeNull();
  });

  test("no runs: no step-metrics query and an empty state", async () => {
    const calls = mockApi(ROUTES);
    renderWithClient(charts({ data: makeTaskRuns({ runs: [], groups: [] }) }), { registry });
    expect(screen.getAllByText("No runs yet").length).toBe(2);
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(stepBodies(calls)).toHaveLength(0);
  });

  test("Save as view writes the shown step-metric sections and opens the new view", async () => {
    const calls = mockApi({
      ...ROUTES,
      [`PUT ${BASE}/views/curves_v1`]: { info: { name: "curves_v1", title: "curves_v1", origin: "file", path: null, kind: null }, view: { title: "curves_v1", panels: [] } },
    });
    const opened: string[] = [];
    renderWithClient(charts({ onOpenView: (n) => opened.push(n), viewNames: ["taken"] }), { registry });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search panels" }), { target: { value: "val/" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as view" }));
    const form = screen.getByRole("form", { name: "Save as view" });
    const name = within(form).getByRole("textbox", { name: "View name" });
    fireEvent.change(name, { target: { value: "taken" } });
    expect(within(form).getByText("taken exists")).toBeTruthy();
    expect((within(form).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(name, { target: { value: "curves_v1" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(opened).toEqual(["curves_v1"]));
    const put = calls.find((c) => c.method === "PUT");
    expect((put?.body as { text: string }).text).toBe(
      ["title: curves_v1", "panels:", "  - type: curves", "    title: val", "    data:", "      metrics: [val/loss, val/top1]", "      group_by: group", ""].join("\n"),
    );
  });

  test("+ Panel offers a custom view", () => {
    mockApi(ROUTES);
    const navigated: string[] = [];
    renderWithClient(charts(), { registry, navigate: (h) => navigated.push(h) });
    fireEvent.click(screen.getByRole("button", { name: "+ Panel" }));
    fireEvent.click(within(screen.getByRole("menu", { name: "Add panel" })).getByRole("menuitem", { name: "Custom view…" }));
    expect(navigated).toEqual([`/t/${PROJECT}/${TASK}/edit/new`]);
  });

  test("+ Panel closes on Escape and on a press outside", () => {
    mockApi(ROUTES);
    renderWithClient(charts(), { registry });
    const button = screen.getByRole("button", { name: "+ Panel" });
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole("menu", { name: "Add panel" }), { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Add panel" })).toBeNull();
    fireEvent.click(button);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu", { name: "Add panel" })).toBeNull();
  });
});

describe("Compare in the Charts tab", () => {
  const EVAL_ROUTES = { [`GET ${BASE}/views/overview`]: presetDoc("generic"), [`POST ${BASE}/views/query`]: query };

  test("eval tasks show Compare first; + Panel → Compare adds one; Save as view stores them", async () => {
    const calls = mockApi({
      ...EVAL_ROUTES,
      [`PUT ${BASE}/views/cmp`]: { info: { name: "cmp", title: "cmp", origin: "file", path: null, kind: null }, view: { title: "cmp", panels: [] } },
    });
    renderWithClient(charts({ data: makeEvalTaskRuns() }), { registry: fakeRegistry(["stat_strip"]) });
    expect(document.querySelector(".panels > section")?.getAttribute("aria-label")).toBe("Compare");
    expect(screen.getAllByRole("region", { name: /^Compare datasets/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "+ Panel" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Compare" }));
    expect(screen.getAllByRole("region", { name: /^Compare datasets/ })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Remove compare panel" }));
    expect(screen.getAllByRole("region", { name: /^Compare datasets/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Save as view" }));
    const form = screen.getByRole("form", { name: "Save as view" });
    fireEvent.change(within(form).getByRole("textbox", { name: "View name" }), { target: { value: "cmp" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect((calls.find((c) => c.method === "PUT")?.body as { text: string }).text).toBe(
      [
        "title: cmp",
        "panels:",
        "  - type: compare",
        '    title: "Compare datasets · model-x"',
        "    data:",
        "      datasets: [test-a, test-b, test-c, test-d]",
        "      model: model-x",
        "      metrics: [top10]",
        "    render: table",
        "",
      ].join("\n"),
    );
  });

  test("the panel search hides Compare panels, and Save as view leaves hidden ones out", () => {
    mockApi(EVAL_ROUTES);
    renderWithClient(charts({ data: makeEvalTaskRuns() }), { registry: fakeRegistry(["stat_strip"]) });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search panels" }), { target: { value: "model-y" } });
    expect(screen.queryByRole("region", { name: "Compare" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save as view" }));
    expect(within(screen.getByRole("form", { name: "Save as view" })).getByText("0 panels")).toBeTruthy();
  });

  test("a task without dataset keys has no Compare and + Panel → Compare is disabled", () => {
    mockApi(ROUTES);
    renderWithClient(charts(), { registry });
    expect(screen.queryByRole("region", { name: "Compare" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "+ Panel" }));
    expect((screen.getByRole("menuitem", { name: "Compare" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
