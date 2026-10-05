import { afterEach, describe, expect, test } from "bun:test";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { PanelRegistryContext } from "../../src/pages/components/PanelGrid";
import type { QueryResponse, ViewDetail, ViewInfo } from "../../src/pages/components/types";
import type { RunRecord } from "../../src/api/models";
import { hostRow } from "../launch/fixtures";
import { Leaderboard as LeaderboardPanel } from "../../src/panels/Leaderboard";
import { TaskPage, boardMeta, reevalLine } from "../../src/pages/Task";
import { REPO, RUN_RF, RUN_SVM, makeBoard, makeDetail, makeRecord } from "./fixtures";
import { type Call, HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const BASE = "/api/v1/tasks/toy-classifier/toy-test";

async function readyNewRun(): Promise<HTMLElement> {
  // Query notifications and initial-host effects both complete inside act.
  for (let tick = 0; tick < 50; tick++) {
    await act(async () => { await new Promise<void>(resolve => setTimeout(resolve, 0)); });
    if (screen.queryByLabelText("Command") && (screen.queryByRole("radio", { name: "local" }) as HTMLInputElement | null)?.checked) break;
  }
  const dialog = screen.getByRole("dialog", { name: "New run" });
  expect(within(dialog).getByLabelText("Command")).toBeTruthy();
  expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true);
  return dialog;
}


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
    [`POST ${BASE}/reeval`]: { evaluated: ["r1", "r2"], skipped: {}, warnings: [] },
    "GET /api/v1/projects/toy-classifier/sweeps": [],
  };
}

const registry = fakeRegistry(["stat_strip", "leaderboard"]);

test("boardMeta counts configs and runs and lists metric versions", () => {
  expect(boardMeta(makeBoard())).toEqual(["2 configs, 6 runs", "accuracy v1", "macro_f1 v1"]);
  expect(boardMeta({ ...makeBoard(), needs_reeval: ["r1"] }).at(-1)).toBe("1 need re-eval");
});

test("reevalLine counts re-scored and skipped runs, with each skip reason", () => {
  expect(reevalLine({ evaluated: ["a", "b"], skipped: {}, warnings: [] })).toBe("2 re-scored");
  expect(reevalLine({ evaluated: [], skipped: { a: "no predictions" }, warnings: [] })).toBe(
    "0 re-scored · 1 skipped: no predictions",
  );
  expect(
    reevalLine({
      evaluated: ["a"],
      skipped: { b: "no predictions", c: "no predictions", d: "metric failed" },
      warnings: ["w1", "w2"],
    }),
  ).toBe("1 re-scored · 3 skipped: no predictions ×2, metric failed ×1 · 2 warnings");
  // a partial answer must not break the line
  expect(reevalLine({} as never)).toBe("0 re-scored");
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
    expect((await screen.findByRole("status", { name: "Re-evaluate" })).textContent).toBe("2 re-scored");
  });

  test("Re-evaluate all says when it re-scored nothing, and why", async () => {
    mockApi({
      ...routes("overview"),
      [`POST ${BASE}/reeval`]: { evaluated: [], skipped: { r9: "no predictions" }, warnings: [] },
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate all" }));
    const status = await screen.findByRole("status", { name: "Re-evaluate" });
    expect(status.textContent).toBe("0 re-scored · 1 skipped: no predictions");
    expect(status.getAttribute("title")).toBe("r9: no predictions");
  });

  const RUNS_URL = "GET /api/v1/runs?project=toy-classifier&task=toy-test&archived=true&limit=1000";

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
      "GET /api/v1/hosts": [hostRow("local", { kind: "local" }, { environment_id: "env-5c1e" })],
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
    };
  }

  test.each([0, 2])("New run opens from the best config and links all launched runs with %i queued", async (queued) => {
    const calls = mockApi({
      ...newRunRoutes(),
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        return makeRecord({
          run_id: `20261003-120000-toy-test-s${seed}`,
          seed,
          status: seed >= 7 - queued ? "queued" : "running",
        });
      },
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));

    const dialog = await readyNewRun();
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
    expect(line.textContent).toBe(`Launched 3 on local${queued ? `, ${queued} queued` : ""}: s4 s5 s6`);
    for (const seed of [4, 5, 6]) {
      expect(within(line).getByRole("link", { name: `s${seed}` }).getAttribute("href")).toBe(
        `/r/20261003-120000-toy-test-s${seed}`,
      );
    }
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

  test("New run opened again after a launch proposes the seeds after the ones it started", async () => {
    const started: RunRecord[] = [];
    const base = newRunRoutes();
    const calls = mockApi({
      ...base,
      // each launch invalidates runs; the reopened dialog must read the new runs, not the cache
      [RUNS_URL]: () => [...(base[RUNS_URL] as RunRecord[]), ...started],
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        const rec = makeRecord({ run_id: `20261003-120000-toy-test-s${seed}`, seed, status: "running" });
        started.push(rec);
        return rec;
      },
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    const launch = async (hypothesis: string): Promise<string> => {
      fireEvent.click(screen.getByRole("button", { name: "New run" }));
      const dialog = await readyNewRun();
      const seeds = (within(dialog).getByLabelText("Seeds") as HTMLInputElement).value;
      await waitFor(() =>
        expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true),
      );
      fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: hypothesis } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));
      await waitFor(() => expect(document.querySelector('[role="dialog"]') === null).toBe(true));
      return seeds;
    };
    expect(await launch("first")).toBe("4, 5, 6");
    expect(await launch("second")).toBe("7, 8, 9");
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([4, 5, 6, 7, 8, 9]);
  });

  test("New run reopened after runs started elsewhere reads the runs again instead of its cache", async () => {
    const elsewhere: RunRecord[] = [];
    const base = newRunRoutes();
    mockApi({ ...base, [RUNS_URL]: () => [...(base[RUNS_URL] as RunRecord[]), ...elsewhere] });
    const { client } = renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    let dialog = await readyNewRun();
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("4, 5, 6");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(document.querySelector('[role="dialog"]') === null).toBe(true));
    // an agent launches seeds 4-6 of the config while the dialog is closed; its run event marks runs stale
    elsewhere.push(...[4, 5, 6].map((seed) => makeRecord({ run_id: `20261003-130000-toy-test-e${seed}`, seed })));
    await act(() => client.invalidateQueries({ queryKey: ["runs"] }));
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    dialog = await readyNewRun();
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("7, 8, 9");
  });

  test("lists the project's sweeps with their best config, each linking its sweep page", async () => {
    mockApi({
      ...routes("overview"),
      "GET /api/v1/projects/toy-classifier/sweeps": [
        {
          id: "s-7f3a",
          created_at: "2026-10-03T09:12:00Z",
          n_runs: 6,
          best: { params: { lr: "3e-4", beam: "10" }, group_id: "g-7e3f", n: 3, mean: 0.9121, lo: 0.9109, hi: 0.9133, run_ids: [] },
        },
        { id: "s-1b2c", created_at: "2026-10-02T09:00:00Z", n_runs: 4, best: null },
      ],
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    const line = await screen.findByLabelText("Sweeps");
    expect(line.textContent).toBe("sweeps: s-7f3a ×6 lr 3e-4, beam 10 0.9121 · s-1b2c ×4");
    expect(within(line).getByRole("link", { name: "s-7f3a" }).getAttribute("href")).toBe("/s/toy-classifier/s-7f3a");
  });

  test("New run reads past the first 1,000 runs: an older seed of the template's config is never proposed", async () => {
    // the newest 1,000 runs belong to other configs; the template's seed 4 is older
    const newest = Array.from({ length: 1000 }, (_, i) =>
      makeRecord({ run_id: `20261001-000000-toy-test-n${i}`, seed: 1, config_hash: "sha256:other" }),
    );
    const older = makeRecord({ run_id: "20260901-000000-toy-test-old4", seed: 4 });
    const last = newest.at(-1);
    const cursor = `before_created_at=${encodeURIComponent(last?.created_at ?? "")}&before_run_id=${last?.run_id}`;
    mockApi({
      ...newRunRoutes(),
      [RUNS_URL]: newest,
      // the next page after the newest 1,000 (keyset); a server without keyset paging
      // answers the newest 4,000 instead, which fetchAllRuns also reads
      [`GET /api/v1/runs?project=toy-classifier&task=toy-test&archived=true&limit=4000&${cursor}`]: [older],
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    const dialog = await readyNewRun();
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("5, 6, 7");
  });

  test("New run counts the seeds of archived runs: an archived seed of the template's config is never proposed", async () => {
    const base = newRunRoutes();
    const archived = makeRecord({ run_id: "20260927-000000-toy-test-arch4", seed: 4, archived: true });
    mockApi({ ...base, [RUNS_URL]: [...(base[RUNS_URL] as RunRecord[]), archived] });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    const dialog = await readyNewRun();
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("5, 6, 7");
  });

  test("a leaderboard update while the dialog is open keeps the dialog and what was typed", async () => {
    mockApi(newRunRoutes());
    const { client } = renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    const dialog = await readyNewRun();
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "svm holds on new seeds" } });
    // a run event: the best config's latest run is now another run, whose read never ends
    const board = makeBoard();
    const [best] = board.rows;
    if (best === undefined) throw new Error("fixture has no rows");
    board.rows = [{ ...best, latest_run_id: "20261004-000000-toy-test-new1" }, ...board.rows.slice(1)];
    await act(async () => {
      client.setQueryData(["leaderboard", "toy-classifier", "toy-test", []], board);
      await new Promise<void>(resolve => setTimeout(resolve, 0));
    });
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
    expect(screen.getByRole("dialog", { name: "New run" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
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
    expect(screen.getByRole("dialog", { name: "New run" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
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

  test("an unknown project shows one not-found state with no actions", async () => {
    const gone = new HttpReply(404, { error: "unknown project 'nope'", type: "StoreError" });
    const NOPE = "/api/v1/tasks/nope/nope";
    mockApi({
      [`GET ${NOPE}/leaderboard`]: gone,
      [`GET ${NOPE}/views`]: gone,
      [`GET ${NOPE}/views/overview`]: gone,
      [`POST ${NOPE}/views/query`]: gone,
    });
    renderWithClient(<TaskPage project="nope" task="nope" />, { registry });
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Not found"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual(["unknown project 'nope'"]);
    expect(screen.queryByRole("navigation", { name: "Views" })).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link", { name: "+ view" })).toBeNull();
    expect(screen.getByRole("link", { name: "All projects" }).getAttribute("href")).toBe("/");
  });

  test("an unknown task in a known project (400 ConfigError) shows the same not-found state", async () => {
    const gone = new HttpReply(400, { error: "unknown task 'nope' in project 'toy-classifier'", type: "ConfigError" });
    const NOPE = "/api/v1/tasks/toy-classifier/nope";
    mockApi({
      [`GET ${NOPE}/leaderboard`]: gone,
      [`GET ${NOPE}/views`]: gone,
      [`GET ${NOPE}/views/overview`]: gone,
      [`POST ${NOPE}/views/query`]: gone,
    });
    renderWithClient(<TaskPage project="toy-classifier" task="nope" />, { registry });
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Not found"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual([
      "unknown task 'nope' in project 'toy-classifier'",
    ]);
    expect(screen.queryByRole("navigation", { name: "Views" })).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  test("another 400 ConfigError is not a not-found state", async () => {
    mockApi({
      ...routes("overview"),
      [`GET ${BASE}/leaderboard`]: new HttpReply(400, { error: "bad metric 'x'", type: "ConfigError" }),
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    expect((await screen.findByRole("alert")).textContent).toBe("bad metric 'x'");
    expect(screen.getByRole("heading", { level: 1 }).textContent).not.toBe("Not found");
  });

  test("a server error on the board is not a not-found state", async () => {
    mockApi({
      ...routes("overview"),
      [`GET ${BASE}/leaderboard`]: new HttpReply(500, { error: "index locked", type: "StoreError" }),
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    expect((await screen.findByRole("alert")).textContent).toBe("index locked");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("toy-test");
    expect(screen.getByRole("button", { name: "Re-evaluate all" })).toBeTruthy();
  });
});

test("unscored count is separate from stale scores and drift cites stored refs", async () => {
  const board = { ...makeBoard(), unscored: ["u1", "u2"], needs_reeval: ["old"], metric_drift: ["accuracy@v1"] };
  expect(boardMeta(board)).toEqual(["2 configs, 6 runs", "accuracy v1", "macro_f1 v1", "1 need re-eval", "2 unscored"]);
  mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: board });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  const warning = await screen.findByRole("img", { name: "Metric source drift" });
  expect(warning.title).toBe("Different stored metric source hashes: accuracy@v1");
});

function selectableBoard(kind: ReturnType<typeof makeBoard>["kind"] = "agent_eval") {
  const board = makeBoard(); board.kind = kind;
  board.rows[0]!.scores = { "accuracy/value": board.rows[0]!.primary!, "macro_f1/value": { ...board.rows[0]!.primary!, mean: 0.8 } };
  return board;
}
function LinkPanel() {
  return <div><a href={`/r/${RUN_SVM}`}>Choose run</a><a href={`/r/${RUN_SVM}?log=stderr`}>Run stderr</a><a href={`/r/${RUN_SVM}#details`}>Run anchor</a><a href="/x/a/b">Examples route</a></div>;
}
test("task metric selection recomputes ranking and panels using actual score keys", async () => {
  const next = { ...selectableBoard(), primary: "macro_f1/value", headline: "F1 ranking" };
  const calls = mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard(), [`GET ${BASE}/leaderboard?primary=macro_f1%2Fvalue`]: next });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  const control = await screen.findByRole("combobox", { name: "Metric" });
  expect(within(control).getAllByRole("option").map(o => (o as HTMLOptionElement).value)).toEqual(["accuracy/value", "macro_f1/value"]);
  fireEvent.change(control, { target: { value: "macro_f1/value" } });
  await screen.findByRole("heading", { name: "F1 ranking" });
  await waitFor(() => expect(calls.some(c => (c.body as {view?: unknown} | undefined)?.view)).toBe(true));
  const changed = calls.find(c => (c.body as {view?: unknown} | undefined)?.view)?.body as {view: {panels: {data: {primary: string}}[]}};
  expect(changed.view.panels.every(p => p.data.primary === "macro_f1/value")).toBe(true);
  expect(within(control).getAllByRole("option")).toHaveLength(2);
});
test("Repeats checkbox hides actual leaderboard seed dots and preserves test intervals and chart grouping", async () => {
  const board = selectableBoard("system_bench");
  const doc = detail(VIEWS[0]!); doc.view.panels![1]!.noise = ["seed", "test_set"];
  doc.view.panels!.push({ type: "curves", title: "Loss", data: { group_by: "config", metrics: ["loss"] } });
  const calls = mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: board, [`GET ${BASE}/views/overview`]: doc,
    [`POST ${BASE}/views/query`]: (call: Call) => {
      const body = call.body as {view?: {panels: {type: string; noise?: string[]}[]}; panel?: unknown};
      if (body.panel) return { panels: [{ type: "table", title: "Raw samples", rows: [], meta: { total: 0 } }] };
      const noise = body.view?.panels.find(panel => panel.type === "leaderboard")?.noise ?? ["seed", "test_set"];
      return { panels: [{ type: "leaderboard", title: "Configs", rows: board.rows, meta: { primary: board.primary, noise } }] };
    },
  });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry: { leaderboard: LeaderboardPanel } });
  const toggle = await screen.findByRole("checkbox", { name: "Repeats" });
  expect((toggle as HTMLInputElement).checked).toBe(true);
  await waitFor(() => expect(document.querySelectorAll("g.seeds circle.seed").length).toBeGreaterThan(0));
  expect(calls.find(c => c.url === `${BASE}/views/query`)?.body).toEqual({ name: "overview" });
  fireEvent.click(toggle);
  await waitFor(() => {
    expect(screen.getByRole("region", { name: "a Configs" })).toBeTruthy();
    expect(document.querySelectorAll("g.seeds circle.seed")).toHaveLength(0);
  });
  const changed = calls.find(c => (c.body as {view?: unknown} | undefined)?.view)?.body as {view: {panels: {noise?: string[]; data?: {group_by?: string}}[]}};
  expect(changed.view.panels[1]!.noise).toEqual(["test_set"]);
  expect(changed.view.panels[2]!.data?.group_by).toBe("config");
  expect(document.querySelectorAll(".whisk").length).toBeGreaterThan(0);
  fireEvent.click(toggle);
  await waitFor(() => expect(document.querySelectorAll("g.seeds circle.seed").length).toBeGreaterThan(0));
});
test("task run selection stays inline while query, hash, and other links navigate normally", async () => {
  const navigated: string[] = [];
  mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard(), [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(), [`GET ${BASE}/kind`]: { kind: "agent_eval", run_view: [] } });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry: { stat_strip: LinkPanel, leaderboard: () => null }, navigate: href => navigated.push(href) });
  fireEvent.click(await screen.findByRole("link", { name: "Choose run" }));
  expect(await screen.findByRole("region", { name: "Selected run" })).toBeTruthy(); expect(navigated).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Close selected run" })); expect(screen.queryByRole("region", { name: "Selected run" })).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "Run stderr" })); fireEvent.click(screen.getByRole("link", { name: "Run anchor" })); fireEvent.click(screen.getByRole("link", { name: "Examples route" }));
  expect(navigated).toEqual([`/r/${RUN_SVM}?log=stderr`, `/r/${RUN_SVM}#details`, "/x/a/b"]);
  fireEvent.click(screen.getByRole("link", { name: "Choose run" }), { ctrlKey: true });
  expect(screen.queryByRole("region", { name: "Selected run" })).toBeNull(); expect(navigated).toHaveLength(3);
});
test("training task mounts run and checkpoint sections; iteration task mounts flips", async () => {
  mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard("training"), "GET /api/v1/runs?project=toy-classifier&task=toy-test&limit=21": [], [`GET ${BASE}`]: { summary: { metrics: {} } } });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  expect(await screen.findByRole("heading", { name: "Training runs" })).toBeTruthy(); expect(screen.getByRole("heading", { name: "Checkpoints" })).toBeTruthy();
  cleanup(); const board = selectableBoard("agent_iteration"); board.rows = [];
  mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: board });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  expect(await screen.findByRole("region", { name: "Iteration example changes" })).toBeTruthy();
});
test("system selected run scopes the mounted raw samples table", async () => {
  const calls = mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard("system_bench"), [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(), [`GET ${BASE}/kind`]: { kind: "system_bench", run_view: [] } });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry: { stat_strip: LinkPanel, leaderboard: () => null } });
  expect(await screen.findByRole("region", { name: "Raw benchmark samples" })).toBeTruthy(); fireEvent.click(await screen.findByRole("link", { name: "Choose run" }));
  await waitFor(() => expect(calls.some(c => (c.body as {panel?: {data?: {filter?: {run_id?: string}}}} | undefined)?.panel?.data?.filter?.run_id === RUN_SVM)).toBe(true));
});

test("metric changes hide previous ranking and panels while recomputation is pending", async () => {
  let finish: ((value: unknown) => void) | undefined;
  mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard(), [`GET ${BASE}/leaderboard?primary=macro_f1%2Fvalue`]: () => new Promise(resolve => { finish = resolve; }) });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  await screen.findByRole("region", { name: "a Best" });
  fireEvent.change(screen.getByRole("combobox", { name: "Metric" }), { target: { value: "macro_f1/value" } });
  expect(screen.queryByRole("region", { name: "a Best" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "SVM +0.037 over rf, p = 0.15" })).toBeNull();
  finish?.({ ...selectableBoard(), primary: "macro_f1/value", headline: "New metric ranking" });
  expect(await screen.findByRole("heading", { name: "New metric ranking" })).toBeTruthy();
  expect(await screen.findByRole("region", { name: "a Best" })).toBeTruthy();
});

test("task scope changes reset metric, seeds and selected run", async () => {
  const nextBase = "/api/v1/tasks/toy-classifier/other";
  const nextBoard = { ...selectableBoard(), task: "other" };
  const calls = mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard(), [`GET ${BASE}/leaderboard?primary=macro_f1%2Fvalue`]: { ...selectableBoard(), primary: "macro_f1/value" }, [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(), [`GET ${BASE}/kind`]: { kind: "agent_eval", run_view: [] }, [`GET ${nextBase}/leaderboard`]: nextBoard, [`GET ${nextBase}/views`]: VIEWS, [`GET ${nextBase}/views/overview`]: detail(VIEWS[0]!), [`POST ${nextBase}/views/query`]: PANELS });
  const custom = { stat_strip: LinkPanel, leaderboard: () => null };
  const rendered = renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry: custom });
  fireEvent.click(await screen.findByRole("link", { name: "Choose run" }));
  await screen.findByRole("region", { name: "Selected run" });
  fireEvent.change(screen.getByRole("combobox", { name: "Metric" }), { target: { value: "macro_f1/value" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Seeds" }));
  rendered.rerender(<QueryClientProvider client={rendered.client}><PanelRegistryContext.Provider value={custom}><TaskPage project="toy-classifier" task="other" /></PanelRegistryContext.Provider></QueryClientProvider>);
  const metric = await screen.findByRole("combobox", { name: "Metric" });
  expect((metric as HTMLSelectElement).value).toBe("accuracy/value");
  expect((screen.getByRole("checkbox", { name: "Seeds" }) as HTMLInputElement).checked).toBe(true);
  expect(screen.queryByRole("region", { name: "Selected run" })).toBeNull();
  expect(calls.some(c => c.url.startsWith(`${nextBase}/leaderboard?primary=`))).toBe(false);
});

test("selected metric only overrides supported panels in a mixed custom view", async () => {
  const doc = detail(VIEWS[0]!);
  const scatter = { type: "scatter" as const, title: "Explicit axes", data: { x: "usage.usd", y: "accuracy/value", group_by: "group" as const } };
  doc.view.panels!.push(scatter, { type: "grid", title: "Examples" });
  const calls = mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard(), [`GET ${BASE}/views/overview`]: doc, [`GET ${BASE}/leaderboard?primary=macro_f1%2Fvalue`]: { ...selectableBoard(), primary: "macro_f1/value" } });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  fireEvent.change(await screen.findByRole("combobox", { name: "Metric" }), { target: { value: "macro_f1/value" } });
  await waitFor(() => expect(calls.some(c => (c.body as {view?: unknown} | undefined)?.view)).toBe(true));
  const changed = calls.find(c => (c.body as {view?: unknown} | undefined)?.view)?.body as {view: {panels: unknown[]}};
  expect(changed.view.panels[2]).toEqual(scatter);
  expect(changed.view.panels[3]).toEqual({ type: "grid", title: "Examples" });
});

test("Seeds checkbox respects custom authored noise and adds only seed visibility", async () => {
  const doc = detail(VIEWS[0]!); doc.view.panels![1]!.noise = [];
  const calls = mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard(), [`GET ${BASE}/views/overview`]: doc });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  const checkbox = await screen.findByRole("checkbox", { name: "Seeds" });
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  expect(calls.find(c => c.url === `${BASE}/views/query`)?.body).toEqual({ name: "overview" });
  fireEvent.click(checkbox);
  await waitFor(() => expect(calls.some(c => (c.body as {view?: unknown} | undefined)?.view)).toBe(true));
  const changed = calls.find(c => (c.body as {view?: unknown} | undefined)?.view)?.body as {view: {panels: {noise?: string[]}[]}};
  expect(changed.view.panels[1]!.noise).toEqual(["seed"]);
  expect((checkbox as HTMLInputElement).checked).toBe(true);
});

test("views without a leaderboard do not expose an inert Seeds control", async () => {
  const doc = detail(VIEWS[0]!); doc.view.panels = [{ type: "stat_strip", title: "Summary" }];
  mockApi({ ...routes("overview"), [`GET ${BASE}/leaderboard`]: selectableBoard(), [`GET ${BASE}/views/overview`]: doc, [`POST ${BASE}/views/query`]: { panels: [{ type: "stat_strip", title: "Summary", rows: [], meta: {} }] } });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  await screen.findByRole("region", { name: "a Summary" });
  expect(screen.queryByRole("checkbox", { name: "Seeds" })).toBeNull();
  expect(screen.getByRole("combobox", { name: "Metric" })).toBeTruthy();
});

function metricLaunchRoutes(): Record<string, unknown> {
  return {
    ...routes("overview"),
    [`GET ${BASE}/leaderboard`]: selectableBoard(),
    [`GET ${BASE}`]: { summary: { project: "toy-classifier", name: "toy-test" }, repo: REPO, dataset: { name: "toyset" }, metrics: {}, stages: {} },
    "GET /api/v1/runs?project=toy-classifier&task=toy-test&archived=true&limit=1000": [],
    "GET /api/v1/hosts": [hostRow("local", { kind: "local" }, { environment_id: "env-5c1e" })],
    "GET /api/v1/gpus": [], "GET /api/v1/queue": [],
    [`GET /api/v1/runs/${RUN_RF}`]: makeDetail({ run_id: RUN_RF, command_template: ["python", "selected_metric.py", "--seed={seed}"] }),
  };
}

test("New run waits for selected ranking before capturing its best template", async () => {
  let finish: ((value: unknown) => void) | undefined;
  const calls = mockApi({ ...metricLaunchRoutes(), [`GET ${BASE}/leaderboard?primary=macro_f1%2Fvalue`]: () => new Promise(resolve => { finish = resolve; }) });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  fireEvent.change(await screen.findByRole("combobox", { name: "Metric" }), { target: { value: "macro_f1/value" } });
  const launch = screen.getByRole("button", { name: "New run" }) as HTMLButtonElement;
  expect(launch.disabled).toBe(true);
  fireEvent.click(launch); expect(screen.queryByRole("dialog")).toBeNull();
  const selected = { ...selectableBoard(), primary: "macro_f1/value", headline: "Selected metric ready" };
  selected.rows[0]!.latest_run_id = RUN_RF;
  await act(async () => { finish?.(selected); await new Promise<void>(resolve => setTimeout(resolve, 0)); });
  await screen.findByRole("heading", { name: "Selected metric ready" });
  expect(launch.disabled).toBe(false); fireEvent.click(launch);
  const dialog = await readyNewRun();
  expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe("python selected_metric.py --seed={seed}");
  expect(calls.some(call => call.url === `/api/v1/runs/${RUN_RF}`)).toBe(true);
});

test("New run remains unavailable when selected ranking fails", async () => {
  mockApi({ ...metricLaunchRoutes(), [`GET ${BASE}/leaderboard?primary=macro_f1%2Fvalue`]: new HttpReply(500, { error: "selected ranking unavailable", type: "StoreError" }) });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  fireEvent.change(await screen.findByRole("combobox", { name: "Metric" }), { target: { value: "macro_f1/value" } });
  await screen.findByRole("alert");
  const launch = screen.getByRole("button", { name: "New run" }) as HTMLButtonElement;
  expect(launch.disabled).toBe(true); fireEvent.click(launch);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a successfully loaded empty leaderboard can open an empty New run draft", async () => {
  const board = selectableBoard(); board.rows = [];
  const calls = mockApi({ ...metricLaunchRoutes(), [`GET ${BASE}/leaderboard`]: board });
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  await screen.findByRole("combobox", { name: "Metric" });
  const launch = screen.getByRole("button", { name: "New run" }) as HTMLButtonElement;
  expect(launch.disabled).toBe(false); fireEvent.click(launch);
  const dialog = await readyNewRun();
  expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe("");
  expect(calls.some(call => /^\/api\/v1\/runs\//.test(call.url))).toBe(false);
});
