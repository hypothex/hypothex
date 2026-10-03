import { afterEach, describe, expect, test } from "bun:test";
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { PanelRegistryContext } from "../../src/pages/components/PanelGrid";
import type { QueryResponse, ViewDetail, ViewInfo } from "../../src/pages/components/types";
import { TaskPage, boardMeta } from "../../src/pages/Task";
import { REPO, RUN_RF, RUN_SVM, makeBoard, makeDetail, makeRecord } from "./fixtures";
import { type Call, HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const BASE = "/api/v1/tasks/toy-classifier/toy-test";

const VIEWS: ViewInfo[] = [
  { name: "overview", title: "Overview", origin: "preset", path: null, kind: "generic" },
  {
    name: "route-quality",
    title: "route quality",
    origin: "file",
    path: "/repo/.hypothex/views/toy-test/route-quality.yaml",
    kind: null,
  },
];

function detail(info: ViewInfo): ViewDetail {
  return {
    info,
    text: `title: ${info.title}\n`,
    view: {
      title: info.title,
      panels: [
        { type: "stat_strip", title: "Best", data: {}, layout: { span: 4, row: null } },
        { type: "leaderboard", title: "All ideas", data: {}, layout: { span: 8, row: null } },
      ],
    },
  };
}

const PANELS: QueryResponse = {
  panels: [
    { type: "stat_strip", title: "Best", rows: [{ label: "solved v2", value: "0.733" }], meta: {} },
    { type: "leaderboard", title: "All ideas", rows: [{}, {}], meta: {} },
  ],
};

function routes(view: string): Record<string, unknown> {
  const info = VIEWS.find((v) => v.name === view) as ViewInfo;
  return {
    [`GET ${BASE}/leaderboard`]: makeBoard(),
    [`GET ${BASE}/views`]: VIEWS,
    [`GET ${BASE}/views/${view}`]: detail(info),
    [`POST ${BASE}/views/query`]: PANELS,
    [`POST ${BASE}/reeval`]: { evaluated: 12 },
  };
}

const registry = fakeRegistry(["stat_strip", "leaderboard"]);

test("boardMeta counts configs and runs and lists metric versions", () => {
  expect(boardMeta(makeBoard())).toEqual(["2 configs, 6 runs", "accuracy v1", "macro_f1 v1"]);
  expect(boardMeta({ ...makeBoard(), needs_reeval: ["r1"] }).at(-1)).toBe("1 need re-eval");
});

describe("TaskPage", () => {
  test("renders headline, tabs, and the active view's lettered panels", async () => {
    const calls = mockApi(routes("route-quality"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" view="route-quality" />, {
      registry,
    });
    const h1 = await screen.findByRole("heading", { level: 1, name: "SVM +0.037 over rf, p = 0.15" });
    expect(h1).toBeTruthy();
    expect(screen.getByText("generic")).toBeTruthy();
    expect(screen.getByText("2 configs, 6 runs")).toBeTruthy();

    const tabs = screen.getByRole("navigation", { name: "Views" });
    const overview = within(tabs).getByRole("link", { name: "Overview preset" });
    expect(overview.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
    expect(overview.getAttribute("aria-current")).toBeNull();
    const active = within(tabs).getByRole("link", { name: "route quality" });
    expect(active.getAttribute("href")).toBe("/t/toy-classifier/toy-test?view=route-quality");
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(within(tabs).getByRole("link", { name: "+ view" }).getAttribute("href")).toBe(
      "/t/toy-classifier/toy-test/edit/new",
    );
    expect(within(tabs).getByRole("link", { name: "Edit" }).getAttribute("href")).toBe(
      "/t/toy-classifier/toy-test/edit/route-quality",
    );

    const best = await screen.findByRole("region", { name: "a Best" });
    expect(best.style.gridColumn).toBe("span 4");
    const ideas = screen.getByRole("region", { name: "b All ideas" });
    expect(ideas.style.gridColumn).toBe("span 8");
    expect(within(ideas).getByTestId("panel-leaderboard").textContent).toBe("All ideas:2");
    expect(within(tabs).getByText("2 panels")).toBeTruthy();

    const query = calls.find((c: Call) => c.url === `${BASE}/views/query`);
    expect(query?.body).toEqual({ name: "route-quality" });
  });

  test("defaults to the overview preset, which has no Edit button", async () => {
    const calls = mockApi(routes("overview"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    const tabs = screen.getByRole("navigation", { name: "Views" });
    expect(within(tabs).getByRole("link", { name: "Overview preset" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(within(tabs).queryByRole("link", { name: "Edit" })).toBeNull();
    expect(calls.find((c) => c.url === `${BASE}/views/query`)?.body).toEqual({ name: "overview" });
  });

  test("Re-evaluate all posts to the task reeval route with a command_id", async () => {
    const calls = mockApi(routes("overview"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate all" }));
    await waitFor(() => expect(calls.some((c) => c.url === `${BASE}/reeval`)).toBe(true));
    const body = calls.find((c) => c.url === `${BASE}/reeval`)?.body as Record<string, unknown>;
    expect(typeof body.command_id).toBe("string");
    expect(body.created_by).toBe("human");
  });

  const RUNS_URL = "GET /api/v1/runs?project=toy-classifier&task=toy-test&limit=1000";

  /** Routes behind the New run dialog: task detail, template run, task runs, hosts. */
  function newRunRoutes(): Record<string, unknown> {
    return {
      ...routes("overview"),
      [`GET ${BASE}`]: {
        summary: { project: "toy-classifier", name: "toy-test" },
        repo: REPO,
        dataset: { name: "toyset" },
        metrics: {},
        stages: {},
      },
      [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(),
      [RUNS_URL]: [
        makeRecord({ run_id: "20260926-200000-toy-test-aa01", seed: 1 }),
        makeRecord({ run_id: "20260926-200100-toy-test-aa02", seed: 2 }),
        makeRecord({ run_id: RUN_RF, seed: 9, config_hash: "sha256:5a810ddb4e0c2f19" }),
      ],
      "GET /api/v1/hosts": [],
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
    };
  }

  test("New run opens the launch dialog from the best config and links the launched runs", async () => {
    const calls = mockApi({
      ...newRunRoutes(),
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        return makeRecord({ run_id: `20261003-120000-toy-test-s${seed}`, seed, status: "running" });
      },
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));

    const dialog = await screen.findByRole("dialog", { name: "New run" });
    expect(within(dialog).getByText("toy-classifier / toy-test")).toBeTruthy();
    expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe(
      "python train_eval.py --model svm --seed={seed}",
    );
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("4, 5, 6");
    await waitFor(() =>
      expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true),
    );
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "svm holds on new seeds" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));

    const line = await waitFor(() => {
      const el = document.querySelector("p.launched");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(line.textContent).toBe("Launched 3 on local: s4 s5 s6");
    expect(within(line).getByRole("link", { name: "s4" }).getAttribute("href")).toBe(
      "/r/20261003-120000-toy-test-s4",
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([4, 5, 6]);
    expect(sent[0]?.body).toMatchObject({
      repo: REPO,
      task: "toy-test",
      command: ["python", "train_eval.py", "--model", "svm", "--seed={seed}"],
      hypothesis: "svm holds on new seeds",
      gpus: 0,
      queue: false,
    });
  });

  test("New run reads past the first 1,000 runs: an older seed of the template's config is never proposed", async () => {
    // the newest 1,000 runs belong to other configs; the template's seed 4 is older
    const newest = Array.from({ length: 1000 }, (_, i) =>
      makeRecord({ run_id: `20261001-000000-toy-test-n${i}`, seed: 1, config_hash: "sha256:other" }),
    );
    const older = makeRecord({ run_id: "20260901-000000-toy-test-old4", seed: 4 });
    mockApi({
      ...newRunRoutes(),
      [RUNS_URL]: newest,
      "GET /api/v1/runs?project=toy-classifier&task=toy-test&limit=4000": [...newest, older],
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    const dialog = await screen.findByRole("dialog", { name: "New run" });
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("5, 6, 7");
  });

  test("a leaderboard update while the dialog is open keeps the dialog and what was typed", async () => {
    mockApi(newRunRoutes());
    const { client } = renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    const dialog = await screen.findByRole("dialog", { name: "New run" });
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "svm holds on new seeds" } });
    // a run event: the best config's latest run is now another run, whose read never ends
    const board = makeBoard();
    const [best] = board.rows;
    if (best === undefined) throw new Error("fixture has no rows");
    board.rows = [{ ...best, latest_run_id: "20261004-000000-toy-test-new1" }, ...board.rows.slice(1)];
    client.setQueryData(["leaderboard", "toy-classifier", "toy-test", []], board);
    await new Promise((resolve) => setTimeout(resolve, 50));
    const still = screen.getByRole("dialog", { name: "New run" });
    expect((within(still).getByLabelText("Hypothesis") as HTMLInputElement).value).toBe("svm holds on new seeds");
    expect((within(still).getByLabelText("Command") as HTMLTextAreaElement).value).toBe(
      "python train_eval.py --model svm --seed={seed}",
    );
  });

  test("New run shows the runs read error instead of a dialog with possibly used seeds", async () => {
    mockApi({
      ...newRunRoutes(),
      [RUNS_URL]: new HttpReply(500, { error: "runs index unreadable", type: "StoreError" }),
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    expect((await screen.findByRole("alert")).textContent).toBe("runs index unreadable");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("New run shows the template run read error instead of a blank dialog", async () => {
    mockApi({
      ...newRunRoutes(),
      [`GET /api/v1/runs/${RUN_SVM}`]: new HttpReply(404, { error: `no run ${RUN_SVM}`, type: "StoreError" }),
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    expect((await screen.findByRole("alert")).textContent).toBe(`no run ${RUN_SVM}`);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("a tab switch does not draw the previous view's panels under the new view", async () => {
    let release: (value: QueryResponse) => void = () => {};
    const pending = new Promise<QueryResponse>((resolve) => {
      release = resolve;
    });
    const OTHER: QueryResponse = {
      panels: [{ type: "leaderboard", title: "Only board", rows: [{}], meta: {} }],
    };
    const otherDetail = detail(VIEWS[1]);
    otherDetail.view.panels = [{ type: "leaderboard", title: "Only board", data: {}, layout: { span: 12, row: null } }];
    mockApi({
      ...routes("overview"),
      [`GET ${BASE}/views/route-quality`]: otherDetail,
      [`POST ${BASE}/views/query`]: (call: Call) =>
        (call.body as { name: string }).name === "overview" ? PANELS : pending,
    });
    const page = (view?: string) => (
      <PanelRegistryContext.Provider value={registry}>
        <QueryClientProvider client={client}>
          <TaskPage project="toy-classifier" task="toy-test" view={view} />
        </QueryClientProvider>
      </PanelRegistryContext.Provider>
    );
    const { rerender, client } = renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, {
      registry,
    });
    await screen.findByRole("region", { name: "a Best" });

    rerender(page("route-quality"));
    const tabs = screen.getByRole("navigation", { name: "Views" });
    await waitFor(() => expect(within(tabs).getByText("1 panel")).toBeTruthy());
    // The new view's detail is in, its panel data is not: the old panels must not show.
    expect(screen.queryAllByRole("region")).toHaveLength(0);

    release(OTHER);
    const board = await screen.findByRole("region", { name: "a Only board" });
    expect(board.style.gridColumn).toBe("span 12");
  });

  test("shows the error for an unknown view", async () => {
    mockApi({
      ...routes("overview"),
      [`GET ${BASE}/views/nope`]: new HttpReply(404, { error: "no view 'nope' for toy-test", type: "StoreError" }),
      [`POST ${BASE}/views/query`]: new HttpReply(404, { error: "no view 'nope' for toy-test", type: "StoreError" }),
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" view="nope" />, { registry });
    expect((await screen.findByRole("alert")).textContent).toBe("no view 'nope' for toy-test");
    expect(screen.queryByRole("region")).toBeNull();
  });
});
