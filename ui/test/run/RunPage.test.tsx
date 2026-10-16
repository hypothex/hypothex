import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { colorFor } from "../../src/lib/color";
import { RunPage } from "../../src/run/RunPage";
import { defaultSelection, visibleIdentities } from "../../src/task/useRunSelection";
import { RUN_RF, RUN_SVM, SVM_HYPOTHESIS, makeDetail } from "../pages/fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { SVM_GROUP, makeTaskRuns, taskRunsRoutes } from "./taskRunsFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TASK = "/api/v1/tasks/toy-classifier/toy-test";

function routes(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(),
    ...taskRunsRoutes(),
    [`GET ${TASK}/kind`]: { kind: "generic", run_view: [] },
    ...extra,
  };
}

const swatch = () => document.querySelector(".rhead .sw") as HTMLElement;

test("header: identity swatch, derived name with seed, status pill, hypothesis, Compare, tabs", async () => {
  mockApi(routes());
  renderWithClient(<RunPage runId={RUN_SVM} />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toContain("model svm · seed 3"));
  expect(swatch().dataset.color).toBe(colorFor(SVM_GROUP, visibleIdentities(defaultSelection(true), makeTaskRuns())));
  expect(document.querySelector(".rhead .pill")?.textContent).toContain("Finished");
  expect(screen.getByText(SVM_HYPOTHESIS)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Compare" }).getAttribute("href")).toBe(`/x/${RUN_RF}/${RUN_SVM}`);
  const tabs = screen.getAllByRole("tab");
  expect(tabs.map((t) => t.textContent)).toEqual(["Overview", "Charts", "Logs", "Files", "Examples"]);
  expect(tabs[0]?.getAttribute("aria-selected")).toBe("true");
  expect(tabs[0]?.getAttribute("href")).toBe(`/r/${RUN_SVM}`);
  expect(tabs[2]?.getAttribute("href")).toBe(`/r/${RUN_SVM}?tab=logs`);
});

test("?tab= picks the tab; an old ?log= link opens Logs", async () => {
  mockApi(routes());
  const view = renderWithClient(<RunPage runId={RUN_SVM} tab="files" />);
  expect((await screen.findByRole("tab", { name: "Files" })).getAttribute("aria-selected")).toBe("true");
  view.unmount();
  renderWithClient(<RunPage runId={RUN_SVM} log="stderr" />);
  expect((await screen.findByRole("tab", { name: "Logs" })).getAttribute("aria-selected")).toBe("true");
});

test("a renamed run shows its name and the derived name on a muted line", async () => {
  const data = makeTaskRuns();
  data.runs = data.runs.map((r) => (r.run_id === RUN_SVM ? { ...r, name: "svm, tuned C", renamed: true } : r));
  mockApi(routes(taskRunsRoutes(data)));
  renderWithClient(<RunPage runId={RUN_SVM} />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("svm, tuned C"));
  expect(screen.getByText("Renamed. Derived name: model svm · seed 3")).toBeTruthy();
});

test("a run without a task: grey swatch, hypothesis name, no Compare, no task requests", async () => {
  const calls = mockApi({ [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail({ task: null }) });
  renderWithClient(<RunPage runId={RUN_SVM} />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("RBF-kernel SVM · seed 3"));
  expect(swatch().dataset.color).toBe("var(--c0)");
  expect(screen.queryByRole("link", { name: "Compare" })).toBeNull();
  expect(calls.some((c) => c.url.startsWith("/api/v1/tasks/") || c.url.startsWith("/api/v1/hosts"))).toBe(false);
});

/** Open the ⋯ menu (if closed) and return one of its items. */
async function menuItem(name: string): Promise<HTMLElement> {
  if (!screen.queryByRole("menu")) fireEvent.click(await screen.findByRole("button", { name: "More actions" }));
  return screen.getByRole("menuitem", { name });
}

test("Re-infer waits for the task's stages: enabled with an infer stage, explained without (UI-F7)", async () => {
  mockApi(routes({ [`GET ${TASK}`]: { stages: { infer: { command: ["python", "infer.py"] } } } }));
  const view = renderWithClient(<RunPage runId={RUN_SVM} />);
  await waitFor(async () => expect((await menuItem("Re-infer")).hasAttribute("disabled")).toBe(false));
  view.unmount();
  mockApi(routes({ [`GET ${TASK}`]: new HttpReply(500, { error: "task unavailable", type: "StoreError" }) }));
  renderWithClient(<RunPage runId={RUN_SVM} />);
  const item = await menuItem("Re-infer");
  await waitFor(() => expect(item.title).toBe("Infer stage not loaded"));
  expect(item.hasAttribute("disabled")).toBe(true);
});

test("an archived run reads the task's runs with archived=true, so it keeps its colour", async () => {
  const data = makeTaskRuns();
  data.runs = data.runs.map((r) => (r.run_id === RUN_SVM ? { ...r, archived: true } : r));
  const calls = mockApi({
    ...routes({ [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail({ archived: true }) }),
    ...taskRunsRoutes(data, true),
  });
  renderWithClient(<RunPage runId={RUN_SVM} />);
  await waitFor(() => expect(swatch().dataset.color).not.toBe("var(--c0)"));
  expect(calls.some((c) => c.url === `${TASK}/runs?archived=true`)).toBe(true);
});

test("a missing run has a Not found heading and a way Home; a 500 is not 'not found'", async () => {
  mockApi({ "GET /api/v1/runs/nope": new HttpReply(404, { error: "no run with id nope", type: "StoreError" }) });
  const view = renderWithClient(<RunPage runId="nope" />);
  expect((await screen.findByRole("heading", { name: "Not found" })).textContent).toBe("Not found");
  expect(screen.getByRole("link", { name: "Home" }).getAttribute("href")).toBe("/");
  expect(screen.getByRole("alert").textContent).toBe("no run with id nope");
  view.unmount();
  mockApi({ "GET /api/v1/runs/nope": new HttpReply(500, { error: "index unavailable", type: "StoreError" }) });
  renderWithClient(<RunPage runId="nope" />);
  expect((await screen.findByRole("alert")).textContent).toBe("index unavailable");
  expect(screen.queryByRole("heading", { name: "Not found" })).toBeNull();
});
