import { afterEach, expect, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { TaskKind, ViewQueryBody } from "../../src/api/models";
import { KindSection } from "../../src/task/KindSection";
import { makeBoard, makeDetail } from "../pages/fixtures";
import { type Call, HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { BASE, PROJECT, TASK, presetDoc } from "./fixtures";

afterEach(restoreFetch);

/** Echo every queried panel back with no rows; a single-panel query is the raw samples table. */
function query(c: Call) {
  const body = c.body as ViewQueryBody;
  if (body.panel) return { panels: [{ type: "table", title: "Raw samples", rows: [], meta: { total: 0 } }] };
  return { panels: (body.view?.panels ?? []).map((p) => ({ type: p.type, title: p.title ?? p.type, rows: [], meta: {} })) };
}
const routes = (kind: Parameters<typeof presetDoc>[0] = "generic") => ({
  [`GET ${BASE}/views/overview`]: presetDoc(kind),
  [`POST ${BASE}/views/query`]: query,
  [`GET /api/v1/runs?project=${PROJECT}&task=${TASK}&limit=21`]: [],
  [`GET ${BASE}`]: { summary: { metrics: {} } },
  "GET /api/v1/runs/run-a1": makeDetail({ run_id: "run-a1" }),
});
const section = (kind: TaskKind, board = makeBoard()) => <KindSection project={PROJECT} task={TASK} kind={kind} board={board} />;
function LinkPanel() {
  return (
    <div>
      <a href="/r/run-a1">Choose run</a>
      <a href="/r/run-a1?log=stderr">Run stderr</a>
      <a href="/x/a/b">Examples route</a>
    </div>
  );
}

test("training: preset panels without the leaderboard and group curves, plus the training tables", async () => {
  const calls = mockApi(routes("training"));
  renderWithClient(section("training"), { registry: fakeRegistry(["stat_strip", "table", "curves"]) });
  const kind = await screen.findByRole("region", { name: "Training" });
  await within(kind).findByRole("region", { name: "Summary" });
  const body = calls.find((c) => c.method === "POST")?.body as ViewQueryBody;
  expect(body.view?.panels?.map((p) => [p.type, p.title])).toEqual([["stat_strip", "Summary"], ["table", "Runs"], ["curves", "Checkpoints"]]);
  expect(within(kind).getByRole("region", { name: "Runs" })).toBeTruthy();
  expect(within(kind).getByRole("region", { name: "Training runs" })).toBeTruthy();
  expect(within(kind).getByRole("region", { name: "Checkpoint metrics" })).toBeTruthy();
});

test("run links in kind panels open the run inline; other links navigate", async () => {
  mockApi({ ...routes(), "GET /api/v1/tasks/toy-classifier/toy-test/kind": { kind: "agent_eval", run_view: [] } });
  const navigated: string[] = [];
  renderWithClient(section("agent_eval"), { registry: { stat_strip: LinkPanel }, navigate: (h) => navigated.push(h) });
  fireEvent.click(await screen.findByRole("link", { name: "Choose run" }));
  expect(await screen.findByRole("region", { name: "Selected run" })).toBeTruthy();
  expect(navigated).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Close selected run" }));
  expect(screen.queryByRole("region", { name: "Selected run" })).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "Run stderr" }));
  fireEvent.click(screen.getByRole("link", { name: "Examples route" }));
  expect(navigated).toEqual(["/r/run-a1?log=stderr", "/x/a/b"]);
});

test("a generic task's run links navigate to the run page", async () => {
  mockApi(routes());
  const navigated: string[] = [];
  renderWithClient(section("generic"), { registry: { stat_strip: LinkPanel }, navigate: (h) => navigated.push(h) });
  fireEvent.click(await screen.findByRole("link", { name: "Choose run" }));
  expect(navigated).toEqual(["/r/run-a1"]);
});

test("system_bench raw samples follow the inline-selected run", async () => {
  const calls = mockApi({ ...routes(), "GET /api/v1/tasks/toy-classifier/toy-test/kind": { kind: "system_bench", run_view: [] } });
  renderWithClient(section("system_bench"), { registry: { stat_strip: LinkPanel } });
  expect(await screen.findByRole("region", { name: "Raw benchmark samples" })).toBeTruthy();
  fireEvent.click(await screen.findByRole("link", { name: "Choose run" }));
  await waitFor(() =>
    expect(calls.some((c) => (c.body as ViewQueryBody | undefined)?.panel?.data?.filter?.run_id === "run-a1")).toBe(true),
  );
});

test("agent_iteration mounts the example changes panel", async () => {
  mockApi(routes());
  const board = { ...makeBoard(), kind: "agent_iteration" as const, rows: [] };
  renderWithClient(section("agent_iteration", board), { registry: fakeRegistry(["stat_strip"]) });
  expect(await screen.findByRole("region", { name: "Iteration example changes" })).toBeTruthy();
});

test("a failed preset read shows its error", async () => {
  mockApi({ ...routes(), [`GET ${BASE}/views/overview`]: new HttpReply(500, { error: "views unreadable", type: "StoreError" }) });
  renderWithClient(section("generic"), { registry: fakeRegistry(["stat_strip"]) });
  expect((await screen.findByRole("alert")).textContent).toBe("views unreadable");
});
