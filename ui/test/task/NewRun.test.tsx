/**
 * The top bar's `New run` on a task route (preflight M22): the Launch dialog prefilled from
 * the best config's latest run, the next unused seeds, and a line linking what it launched.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { RunRecord } from "../../src/api/models";
import { hostRow } from "../launch/fixtures";
import { REPO, RUN_RF, RUN_SVM, makeBoard, makeDetail, makeRecord } from "../pages/fixtures";
import { type Call, HttpReply, mockApi, restoreFetch } from "../pages/helpers";
import { renderApp } from "../render-app";
import { toyTaskRuns } from "./fixtures";

const BASE = "/api/v1/tasks/toy-classifier/toy-test";
const PATH = "/t/toy-classifier/toy-test";
const RUNS_URL = "GET /api/v1/runs?project=toy-classifier&task=toy-test&archived=true&limit=1000";
const TASK_DETAIL = { summary: { project: "toy-classifier", name: "toy-test", metrics: {} }, repo: REPO, dataset: { name: "toyset" }, metrics: {}, stages: {} };

afterEach(() => {
  cleanup();
  restoreFetch();
});

/** The task page's reads, plus what the dialog reads: template run, task runs, hosts. */
function routes(): Record<string, unknown> {
  return {
    [`GET ${BASE}/runs`]: toyTaskRuns(),
    [`GET ${BASE}/leaderboard`]: makeBoard(),
    [`GET ${BASE}/views`]: [],
    [`GET ${BASE}`]: TASK_DETAIL,
    "GET /api/v1/projects/toy-classifier/sweeps": [],
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

/** The app at the task page; dialog reads are not retried (a 500 shows at once). */
function page() {
  const app = renderApp(PATH);
  app.queryClient.setDefaultOptions({ queries: { ...app.queryClient.getDefaultOptions().queries, retry: false } });
  return app;
}
/** The shell's top bar (the task page's own `header` is a second banner to Testing Library). */
const topBar = (): HTMLElement => document.querySelector("header.top") as HTMLElement;
const newRun = () => within(topBar()).getByRole("button", { name: "New run" }) as HTMLButtonElement;
async function ready(): Promise<void> {
  await waitFor(() => expect(newRun().disabled).toBe(false));
}
async function readyDialog(): Promise<HTMLElement> {
  for (let tick = 0; tick < 50; tick++) {
    await act(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    if (screen.queryByLabelText("Command") && (screen.queryByRole("radio", { name: "local" }) as HTMLInputElement | null)?.checked) break;
  }
  const dialog = screen.getByRole("dialog", { name: "New run" });
  expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true);
  return dialog;
}

describe("New run on a task route", () => {
  test.each([0, 2])("opens from the best config and links all launched runs with %i queued", async (queued) => {
    const calls = mockApi({
      ...routes(),
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        return makeRecord({ run_id: `20261003-120000-toy-test-s${seed}`, seed, status: seed >= 7 - queued ? "queued" : "running" });
      },
    });
    const { router } = page();
    await ready();
    expect(newRun().getAttribute("title")).toBe("New run in toy-classifier / toy-test, from the best config");
    fireEvent.click(newRun());
    const dialog = await readyDialog();
    expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe("python train_eval.py --model svm --seed={seed}");
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("4, 5, 6");
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "svm holds on new seeds" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));
    const line = await waitFor(() => {
      const el = document.querySelector("p.launched");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(line.textContent).toBe(`Launched 3 on local${queued ? `, ${queued} queued` : ""}: s4 s5 s6`);
    expect(within(line).getByRole("link", { name: "s4" }).getAttribute("href")).toBe("/r/20261003-120000-toy-test-s4");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(router.state.location.pathname).toBe(PATH);
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([4, 5, 6]);
  });

  test("opened again after a launch, it proposes the seeds after the ones it started", async () => {
    const started: RunRecord[] = [];
    const base = routes();
    mockApi({
      ...base,
      [RUNS_URL]: () => [...(base[RUNS_URL] as RunRecord[]), ...started],
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        const rec = makeRecord({ run_id: `20261003-120000-toy-test-s${seed}`, seed, status: "running" });
        started.push(rec);
        return rec;
      },
    });
    page();
    await ready();
    const launch = async (hypothesis: string): Promise<string> => {
      fireEvent.click(newRun());
      const dialog = await readyDialog();
      const seeds = (within(dialog).getByLabelText("Seeds") as HTMLInputElement).value;
      fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: hypothesis } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));
      await waitFor(() => expect(document.querySelector('[role="dialog"]') === null).toBe(true));
      return seeds;
    };
    expect(await launch("first")).toBe("4, 5, 6");
    expect(await launch("second")).toBe("7, 8, 9");
  });

  test("a leaderboard update while the dialog is open keeps the dialog and what was typed", async () => {
    mockApi(routes());
    const { queryClient } = page();
    await ready();
    fireEvent.click(newRun());
    const dialog = await readyDialog();
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "svm holds on new seeds" } });
    const board = makeBoard();
    const [best] = board.rows;
    if (best === undefined) throw new Error("fixture has no rows");
    board.rows = [{ ...best, latest_run_id: "20261004-000000-toy-test-new1" }, ...board.rows.slice(1)];
    await act(async () => {
      queryClient.setQueryData(["leaderboard", "toy-classifier", "toy-test", []], board);
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    const still = screen.getByRole("dialog", { name: "New run" });
    expect((within(still).getByLabelText("Hypothesis") as HTMLInputElement).value).toBe("svm holds on new seeds");
  });

  test("a runs read error or a template read error shows in the dialog, not a draft", async () => {
    mockApi({ ...routes(), [RUNS_URL]: new HttpReply(500, { error: "runs index unreadable", type: "StoreError" }) });
    page();
    await ready();
    fireEvent.click(newRun());
    expect((await within(screen.getByRole("dialog", { name: "New run" })).findByRole("alert")).textContent).toBe("runs index unreadable");
    fireEvent.click(within(screen.getByRole("dialog", { name: "New run" })).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    cleanup();
    mockApi({ ...routes(), [`GET /api/v1/runs/${RUN_SVM}`]: new HttpReply(404, { error: `no run ${RUN_SVM}`, type: "StoreError" }) });
    page();
    await ready();
    fireEvent.click(newRun());
    expect((await within(screen.getByRole("dialog", { name: "New run" })).findByRole("alert")).textContent).toBe(`no run ${RUN_SVM}`);
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  test("an empty leaderboard opens an empty draft and reads no template", async () => {
    const calls = mockApi({ ...routes(), [`GET ${BASE}/leaderboard`]: { ...makeBoard(), rows: [] }, [RUNS_URL]: [] });
    page();
    await ready();
    fireEvent.click(newRun());
    const dialog = await readyDialog();
    expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe("");
    expect(calls.some((call) => /^\/api\/v1\/runs\/[^?]/.test(call.url))).toBe(false);
  });

  test("stays unavailable while the leaderboard fails: no template, no seeds", async () => {
    mockApi({ ...routes(), [`GET ${BASE}/leaderboard`]: new HttpReply(400, { error: "bad metric 'x'", type: "ConfigError" }) });
    page();
    await screen.findByText("bad metric 'x'");
    expect(newRun().disabled).toBe(true);
    expect(newRun().getAttribute("title")).toBe("New run unavailable: bad metric 'x'");
  });
});
