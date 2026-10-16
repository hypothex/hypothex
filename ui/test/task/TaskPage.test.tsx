import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ViewDocument, ViewInfo } from "../../src/api/models";
import { TaskPage } from "../../src/task/TaskPage";
import { REPO, RUN_SVM, makeBoard } from "../pages/fixtures";
import { HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { toyTaskRuns } from "./fixtures";

const BASE = "/api/v1/tasks/toy-classifier/toy-test";
const PATH = "/t/toy-classifier/toy-test";
beforeEach(() => window.history.replaceState(null, "", PATH));
afterEach(() => {
  cleanup();
  restoreFetch();
});

const VIEWS: ViewInfo[] = [
  { name: "overview", title: "Overview", origin: "preset", path: null, kind: "generic" },
  { name: "route-quality", title: "route quality", origin: "file", path: "/repo/.hypothex/views/toy-test/route-quality.yaml", kind: null },
];
const detail = (info: ViewInfo): ViewDocument => ({
  info,
  text: `title: ${info.title}\n`,
  view: {
    title: info.title,
    panels: [
      { type: "stat_strip", title: "Best", data: {}, layout: { span: 4, row: null } },
      { type: "leaderboard", title: "All ideas", data: {}, layout: { span: 8, row: null } },
    ],
  },
});
const PANELS = {
  panels: [
    { type: "stat_strip", title: "Best", rows: [{ label: "solved v2", value: "0.733" }], meta: {} },
    { type: "leaderboard", title: "All ideas", rows: [{}, {}], meta: {} },
  ],
};
const TASK_DETAIL = { summary: { project: "toy-classifier", name: "toy-test", metrics: {} }, repo: REPO, dataset: { name: "toyset" }, metrics: {}, stages: {} };

function routes(): Record<string, unknown> {
  return {
    [`GET ${BASE}/runs`]: toyTaskRuns(),
    [`GET ${BASE}/leaderboard`]: makeBoard(),
    [`GET ${BASE}/views`]: VIEWS,
    [`GET ${BASE}/views/overview`]: detail(VIEWS[0] as ViewInfo),
    [`GET ${BASE}/views/route-quality`]: detail(VIEWS[1] as ViewInfo),
    [`POST ${BASE}/views/query`]: PANELS,
    [`POST ${BASE}/reeval`]: { evaluated: ["r1", "r2"], skipped: {}, warnings: [] },
    [`GET ${BASE}`]: TASK_DETAIL,
    "GET /api/v1/projects/toy-classifier/sweeps": [],
  };
}

const registry = fakeRegistry(["stat_strip", "leaderboard"]);
const page = (project = "toy-classifier", task = "toy-test") =>
  renderWithClient(<TaskPage project={project} task={task} />, { registry });
async function ready(): Promise<void> {
  await screen.findByRole("complementary", { name: "Runs" });
}

describe("header", () => {
  test("name, kind, facts line with the best run linked", async () => {
    mockApi(routes());
    page();
    await ready();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("toy-test");
    expect(screen.getByTitle("task kind").textContent).toBe("generic");
    const facts = document.querySelector(".facts") as HTMLElement;
    for (const text of ["Primary accuracy ↑", "Best 0.9210 model svm", "4 runs · 2 configs", "toyset"]) {
      expect(facts.textContent).toContain(text);
    }
    expect(within(facts).getByRole("link", { name: "model svm" }).getAttribute("href")).toBe(`/r/${RUN_SVM}`);
    expect(within(facts).getByTitle("accuracy v1, macro_f1 v1")).toBeTruthy();
  });

  test("re-eval backlog, unscored runs and metric drift", async () => {
    mockApi({ ...routes(), [`GET ${BASE}/leaderboard`]: { ...makeBoard(), needs_reeval: ["old"], unscored: ["u1", "u2"], metric_drift: ["accuracy@v1"] } });
    page();
    const drift = await screen.findByRole("img", { name: "Metric source drift" });
    expect(drift.getAttribute("title")).toBe("Different stored metric source hashes: accuracy@v1");
    expect(screen.getByText("1 need re-eval")).toBeTruthy();
    expect(screen.getByText("2 unscored")).toBeTruthy();
  });

  test("Re-evaluate all posts with a command_id and says what it re-scored", async () => {
    const calls = mockApi(routes());
    page();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate all" }));
    expect((await screen.findByRole("status", { name: "Re-evaluate" })).textContent).toBe("2 re-scored");
    const body = calls.find((c) => c.url === `${BASE}/reeval`)?.body as Record<string, unknown>;
    expect(typeof body.command_id).toBe("string");
    expect(body.created_by).toBe("human");
  });

  test("Re-evaluate all says when it re-scored nothing, and why", async () => {
    mockApi({ ...routes(), [`POST ${BASE}/reeval`]: { evaluated: [], skipped: { r9: "no predictions" }, warnings: [] } });
    page();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate all" }));
    const status = await screen.findByRole("status", { name: "Re-evaluate" });
    expect(status.textContent).toBe("0 re-scored · 1 skipped: no predictions");
    expect(status.getAttribute("title")).toBe("r9: no predictions");
  });

  test("lists the project's sweeps with their best config", async () => {
    mockApi({
      ...routes(),
      "GET /api/v1/projects/toy-classifier/sweeps": [
        { id: "s-7f3a", created_at: "2026-10-03T09:12:00Z", n_runs: 6, best: { params: { lr: "3e-4", beam: "10" }, group_id: "g-7e3f", n: 3, mean: 0.9121, lo: 0.9109, hi: 0.9133, run_ids: [] } },
        { id: "s-1b2c", created_at: "2026-10-02T09:00:00Z", n_runs: 4, best: null },
      ],
    });
    page();
    const line = await screen.findByLabelText("Sweeps");
    expect(line.textContent).toBe("sweeps: s-7f3a ×6 lr 3e-4, beam 10 0.9121 · s-1b2c ×4");
    expect(within(line).getByRole("link", { name: "s-7f3a" }).getAttribute("href")).toBe("/s/toy-classifier/s-7f3a");
  });
});

describe("tabs", () => {
  test("the Runs tab shows the runs table", async () => {
    mockApi(routes());
    page();
    await ready();
    fireEvent.click(screen.getByRole("tab", { name: "Runs 4" }));
    expect(window.location.search).toBe("?tab=runs");
    expect(within(screen.getByRole("table", { name: "Runs" })).getAllByRole("link").map((a) => a.textContent)).toEqual(["model svm", "model rf"]);
  });

  test("Charts, Examples and each saved view; + View opens the editor", async () => {
    mockApi(routes());
    page();
    await ready();
    const tabs = screen.getByRole("tablist", { name: "Task" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Charts", "Runs4", "Examples", "route quality"]);
    expect(within(tabs).getByRole("tab", { name: "Charts" }).getAttribute("aria-selected")).toBe("true");
    const custom = within(tabs).getByRole("tab", { name: "route quality" });
    expect(custom.getAttribute("href")).toBe(`${PATH}?tab=view%3Aroute-quality`);
    expect(screen.getByRole("link", { name: "+ View" }).getAttribute("href")).toBe(`${PATH}/edit/new`);
    fireEvent.click(custom);
    expect(window.location.search).toBe("?tab=view%3Aroute-quality");
    expect(await screen.findByRole("link", { name: "Edit" })).toBeTruthy();
    expect(within(tabs).getByRole("tab", { name: "route quality" }).getAttribute("aria-selected")).toBe("true");
  });

  test("a legacy ?view= link opens the view; the run selection survives switching tabs", async () => {
    window.history.replaceState(null, "", `${PATH}?view=route-quality&filter=svm`);
    mockApi(routes());
    page();
    expect(await screen.findByRole("link", { name: "Edit" })).toBeTruthy();
    const charts = screen.getByRole("tab", { name: "Charts" });
    expect(charts.getAttribute("href")).toBe(`${PATH}?filter=svm`);
    fireEvent.click(charts);
    expect(window.location.search).toBe("?filter=svm");
    expect(((await screen.findByRole("searchbox", { name: "Filter runs" })) as HTMLInputElement).value).toBe("svm");
  });

  test("Charts shows the runs sidebar and the kind section", async () => {
    mockApi(routes());
    page();
    await ready();
    const sidebar = screen.getByRole("complementary", { name: "Runs" });
    const rows = within(within(sidebar).getByRole("list", { name: "Run list" })).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".rn-t")?.textContent)).toEqual(["model svm", "model rf"]);
    expect(await screen.findByRole("region", { name: "Summary" })).toBeTruthy();
  });
});

describe("not found", () => {
  test("an unknown project shows one not-found state with no actions", async () => {
    const gone = new HttpReply(404, { error: "unknown project 'nope'", type: "StoreError" });
    const NOPE = "/api/v1/tasks/nope/nope";
    mockApi({ [`GET ${NOPE}/runs`]: gone, [`GET ${NOPE}/leaderboard`]: gone, [`GET ${NOPE}/views`]: gone, [`GET ${NOPE}`]: gone });
    page("nope", "nope");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Not found"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual(["unknown project 'nope'"]);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("link", { name: "All projects" }).getAttribute("href")).toBe("/");
  });

  test("an unknown task in a known project (400 ConfigError) is the same state", async () => {
    const gone = new HttpReply(400, { error: "unknown task 'nope' in project 'toy-classifier'", type: "ConfigError" });
    const NOPE = "/api/v1/tasks/toy-classifier/nope";
    mockApi({ [`GET ${NOPE}/runs`]: gone, [`GET ${NOPE}/leaderboard`]: gone, [`GET ${NOPE}/views`]: gone, [`GET ${NOPE}`]: gone, "GET /api/v1/projects/toy-classifier/sweeps": [] });
    page("toy-classifier", "nope");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Not found"));
    expect(screen.queryByRole("button")).toBeNull();
  });

  test("another 400 ConfigError or a server error on the board is not a not-found state", async () => {
    mockApi({ ...routes(), [`GET ${BASE}/leaderboard`]: new HttpReply(400, { error: "bad metric 'x'", type: "ConfigError" }) });
    page();
    expect(await screen.findByText("bad metric 'x'")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("toy-test");
    cleanup();
    mockApi({ ...routes(), [`GET ${BASE}/leaderboard`]: new HttpReply(500, { error: "index locked", type: "StoreError" }) });
    page();
    expect(await screen.findByText("index locked")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Re-evaluate all" })).toBeTruthy();
  });
});
