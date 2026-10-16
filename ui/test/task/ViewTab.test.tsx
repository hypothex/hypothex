import { afterEach, expect, test } from "bun:test";
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { PanelSpec, ViewDocument, ViewInfo, ViewSpec } from "../../src/api/models";
import { PanelRegistryContext } from "../../src/pages/components/PanelGrid";
import { ViewTab } from "../../src/task/ViewTab";
import { makeBoard } from "../pages/fixtures";
import { type Call, HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { BASE, PROJECT, TASK } from "./fixtures";

afterEach(restoreFetch);

const INFO: ViewInfo = { name: "route-quality", title: "route quality", origin: "file", path: "/repo/.hypothex/views/toy-task/route-quality.yaml", kind: null };
const doc = (panels: PanelSpec[], info: ViewInfo = INFO): ViewDocument => ({ info, text: `title: ${info.title}\n`, view: { title: info.title, panels } });
const PANELS: PanelSpec[] = [
  { type: "stat_strip", title: "Best", data: {}, layout: { span: 4, row: null } },
  { type: "leaderboard", title: "All ideas", data: {}, layout: { span: 8, row: null } },
];
const RESULTS = {
  panels: [
    { type: "stat_strip", title: "Best", rows: [{}], meta: {} },
    { type: "leaderboard", title: "All ideas", rows: [{}, {}], meta: {} },
  ],
};
const registry = fakeRegistry(["stat_strip", "leaderboard", "scatter", "grid"]);
const tab = (name = "route-quality", board = makeBoard(), info: ViewInfo | undefined = INFO) => (
  <ViewTab key={name} project={PROJECT} task={TASK} name={name} board={board} info={info} />
);
const sentView = (calls: Call[]) => calls.find((c) => (c.body as { view?: unknown } | undefined)?.view)?.body as { view: ViewSpec } | undefined;
function selectableBoard() {
  const board = makeBoard();
  const first = board.rows[0];
  if (!first?.primary) throw new Error("fixture");
  first.scores = { "accuracy/value": first.primary, "macro_f1/value": { ...first.primary, mean: 0.8 } };
  return board;
}

test("panels in chrome, Edit link, panel count, queried by name", async () => {
  const calls = mockApi({ [`GET ${BASE}/views/route-quality`]: doc(PANELS), [`POST ${BASE}/views/query`]: RESULTS });
  renderWithClient(tab(), { registry });
  const ideas = await screen.findByRole("region", { name: "All ideas" });
  expect(within(ideas).getByTestId("panel-leaderboard").textContent).toBe("All ideas:2");
  expect(screen.getByRole("region", { name: "Best" })).toBeTruthy();
  expect(screen.getByText("2 panels")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Edit" }).getAttribute("href")).toBe(`/t/${PROJECT}/${TASK}/edit/route-quality`);
  expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "route-quality" });
});

test("switching views never draws the previous view's panels", async () => {
  let release: (v: unknown) => void = () => {};
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  const other: ViewInfo = { ...INFO, name: "other", title: "other" };
  mockApi({
    [`GET ${BASE}/views/route-quality`]: doc(PANELS),
    [`GET ${BASE}/views/other`]: doc([{ type: "leaderboard", title: "Only board", layout: { span: 12, row: null } }], other),
    [`POST ${BASE}/views/query`]: (c: Call) => ((c.body as { name: string }).name === "route-quality" ? RESULTS : pending),
  });
  const view = renderWithClient(tab(), { registry });
  await screen.findByRole("region", { name: "Best" });
  view.rerender(
    <PanelRegistryContext.Provider value={registry}>
      <QueryClientProvider client={view.client}>{tab("other", makeBoard(), other)}</QueryClientProvider>
    </PanelRegistryContext.Provider>,
  );
  await waitFor(() => expect(screen.getByText("1 panel")).toBeTruthy());
  expect(screen.queryByRole("region", { name: "Best" })).toBeNull();
  release({ panels: [{ type: "leaderboard", title: "Only board", rows: [{}], meta: {} }] });
  expect(await screen.findByRole("region", { name: "Only board" })).toBeTruthy();
});

test("an unknown view shows the server's error and no panels", async () => {
  const gone = new HttpReply(404, { error: "no view 'nope' for toy-task", type: "StoreError" });
  mockApi({ [`GET ${BASE}/views/nope`]: gone, [`POST ${BASE}/views/query`]: gone });
  renderWithClient(tab("nope", makeBoard(), undefined), { registry });
  expect((await screen.findByRole("alert")).textContent).toBe("no view 'nope' for toy-task");
  expect(screen.queryByRole("region")).toBeNull();
});

test("the Metric select overrides leaderboard and stat_strip panels only", async () => {
  const scatter: PanelSpec = { type: "scatter", title: "Explicit axes", data: { x: "usage.usd", y: "accuracy/value", group_by: "group" } };
  const calls = mockApi({
    [`GET ${BASE}/views/route-quality`]: doc([...PANELS, scatter, { type: "grid", title: "Examples" }]),
    [`POST ${BASE}/views/query`]: RESULTS,
  });
  renderWithClient(tab("route-quality", selectableBoard()), { registry });
  const control = await screen.findByRole("combobox", { name: "Metric" });
  expect(within(control).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual(["accuracy/value", "macro_f1/value"]);
  fireEvent.change(control, { target: { value: "macro_f1/value" } });
  await waitFor(() => expect(sentView(calls)).toBeTruthy());
  const sent = sentView(calls);
  expect(sent?.view.panels?.map((p) => p.data?.primary)).toEqual(["macro_f1/value", "macro_f1/value", undefined, undefined]);
  expect(sent?.view.panels?.[2]).toEqual(scatter);
});

test("the Seeds checkbox follows authored noise and adds only seed visibility", async () => {
  const calls = mockApi({
    [`GET ${BASE}/views/route-quality`]: doc([PANELS[0] as PanelSpec, { ...(PANELS[1] as PanelSpec), noise: [] }]),
    [`POST ${BASE}/views/query`]: RESULTS,
  });
  renderWithClient(tab(), { registry });
  const box = (await screen.findByRole("checkbox", { name: "Seeds" })) as HTMLInputElement;
  expect(box.checked).toBe(false);
  fireEvent.click(box);
  await waitFor(() => expect(sentView(calls)).toBeTruthy());
  expect(sentView(calls)?.view.panels?.[1]?.noise).toEqual(["seed"]);
  expect(box.checked).toBe(true);
});

test("system_bench calls it Repeats; a view without a leaderboard has no checkbox", async () => {
  mockApi({ [`GET ${BASE}/views/route-quality`]: doc(PANELS), [`POST ${BASE}/views/query`]: RESULTS });
  const bench = { ...makeBoard(), kind: "system_bench" as const };
  const first = renderWithClient(tab("route-quality", bench), { registry });
  expect(await screen.findByRole("checkbox", { name: "Repeats" })).toBeTruthy();
  first.unmount();
  mockApi({
    [`GET ${BASE}/views/route-quality`]: doc([{ type: "stat_strip", title: "Summary" }]),
    [`POST ${BASE}/views/query`]: { panels: [{ type: "stat_strip", title: "Summary", rows: [], meta: {} }] },
  });
  renderWithClient(tab(), { registry });
  await screen.findByRole("region", { name: "Summary" });
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.getByRole("combobox", { name: "Metric" })).toBeTruthy();
});
