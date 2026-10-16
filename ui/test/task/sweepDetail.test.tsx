import { afterEach, describe, expect, setSystemTime, test } from "bun:test";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { SweepDetail, sweepRunsQuery } from "../../src/task/SweepDetail";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { HOSTS, NOW, PROJECT, RUNS, SWEEP_ID, SWEEP_TAG, TASK, makeSummary, makeSweepBoard, rid } from "../pages/sweepFixtures";
import { makeTaskRun, makeTaskRuns } from "./fixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const SWEEP = `/api/v1/sweeps/${PROJECT}/${SWEEP_ID}`;
const RUNS_URL = "/api/v1/runs?project=rxn&tag=sweep%3A0a1b2c3d%3As-7f3a&archived=true&limit=1000";

function routes(summary = makeSummary(), runs: unknown = RUNS): Record<string, unknown> {
  return {
    [`GET ${SWEEP}`]: summary,
    [`GET ${RUNS_URL}`]: runs,
    "GET /api/v1/hosts": HOSTS,
    [`GET /api/v1/tasks/${PROJECT}/${TASK}/leaderboard`]: makeSweepBoard(),
    [`POST ${SWEEP}/cancel_queued`]: summary,
    [`POST ${SWEEP}/extend`]: summary,
  };
}

function statValue(label: string): string | null | undefined {
  const stats = document.querySelector(".sweep-stats dl.stats") as HTMLElement;
  return within(stats).getByText(label).parentElement?.querySelector("dd")?.textContent;
}

const renderDetail = (sweepId = SWEEP_ID) => renderWithClient(<SweepDetail project={PROJECT} sweepId={sweepId} now={NOW} />);
const heading = (name = SWEEP_ID) => screen.findByRole("heading", { level: 2, name });

describe("SweepDetail", () => {
  test("a failed initial run read leaves an error in its panel, not an endless loading state", async () => {
    mockApi(routes(makeSummary(), new HttpReply(400, { error: "runs unavailable", type: "IndexError" })));
    renderDetail();
    await screen.findByText("runs unavailable");
    const panel = screen.getByRole("region", { name: "Runs on hosts" });
    expect(within(panel).getByRole("alert").textContent).toBe("runs unavailable");
    expect(within(panel).queryByText("loading…") === null).toBe(true);
    expect(statValue("cost, — GPU-h")).toBe("$12.50");
  });

  test("run-dependent panels and GPU hours stay loading until the runs arrive", async () => {
    let release: (runs: typeof RUNS) => void = () => {};
    const pending = new Promise<typeof RUNS>((resolve) => {
      release = resolve;
    });
    mockApi(routes(makeSummary(), () => pending));
    renderDetail();
    await heading();
    const panel = screen.getByRole("region", { name: "Runs on hosts" });
    expect(within(panel).getByText("loading…")).toBeTruthy();
    expect(statValue("cost, · GPU-h")).toBe("$12.50");
    expect(document.querySelector('.sweep-head [title="Hosts"]')?.textContent).toBe("loading hosts…");
    await act(async () => {
      release(RUNS);
      await pending;
    });
    await waitFor(() => expect(statValue("cost, 11 GPU-h")).toBe("$12.50"));
    expect(within(panel).queryByText("loading…") === null).toBe(true);
  });

  test("sweepRunsQuery asks for every run with the sweep's member tag, archived included", () => {
    expect(sweepRunsQuery("rxn", SWEEP_TAG)).toEqual({ project: "rxn", tag: "sweep:0a1b2c3d:s-7f3a", archived: true });
  });

  test("header, stats, progress, cells table, what matters, best cell, runs on hosts", async () => {
    mockApi(routes());
    renderDetail();
    expect(await heading()).toBeTruthy();
    await waitFor(() => expect(statValue("best top1")).toBe("0.9120"));
    await waitFor(() => expect(statValue("cost, 11 GPU-h")).toBe("$12.50"));
    expect(statValue("95% CI")).toBe("0.908–0.916");
    expect(statValue("finished")).toBe("5 / 8");
    expect(statValue("ETA")).toBe("1h 30m");
    expect(screen.getByText("lr 2 × beam 2 × 2 seeds").parentElement?.textContent).toBe("lr 2 × beam 2 × 2 seeds = 8");
    expect(await screen.findByText("gpu1, dgx")).toBeTruthy();
    for (const text of ["2 GPU / run", "09:12 UTC"]) expect(screen.getByText(text)).toBeTruthy();
    expect(screen.getByRole("img", { name: "5 finished, 1 running, 1 queued, 1 failed" })).toBeTruthy();
    const cells = screen.getByRole("region", { name: "Mean top1 per cell" });
    expect(within(cells).getByRole("table", { name: "Mean top1 by lr and beam" })).toBeTruthy();
    expect(within(cells).getByRole("link", { name: "d1" }).getAttribute("href")).toBe(`/r/${rid("d1")}`);
    const matters = screen.getByRole("region", { name: "What matters" });
    expect(within(matters).getByText("lr")).toBeTruthy();
    expect(within(matters).getByText("seed")).toBeTruthy();
    const best = screen.getByRole("region", { name: "Best cell" });
    for (const text of ["lr 3e-4, beam 10", "0.9120", "+0.0080 over lr 3e-4, beam 5", "intervals overlap"]) expect(best.textContent).toContain(text);
    const hosts = screen.getByRole("region", { name: "Runs on hosts" });
    expect(await within(hosts).findByText("stale 4m")).toBeTruthy();
    expect(within(hosts).getByText("1 running, 1 queued")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Parallel coordinates" })).toBeNull();
  });

  test("with the task's runs, parallel coordinates draw one line per finished sweep run", async () => {
    mockApi(routes());
    const data = makeTaskRuns({ runs: [makeTaskRun({ run_id: rid("a1"), sweep_id: SWEEP_ID, params: { lr: "1e-4", beam: "5" }, primary: 0.89 }), makeTaskRun({ run_id: rid("d1"), sweep_id: SWEEP_ID, params: { lr: "3e-4", beam: "10" }, primary: 0.912 })] });
    renderWithClient(<SweepDetail project={PROJECT} sweepId={SWEEP_ID} now={NOW} data={data} />);
    expect(await screen.findByRole("region", { name: "Parallel coordinates" })).toBeTruthy();
  });

  test("a one-param sweep without a task uses the table and asks for no leaderboard", async () => {
    const cellRaw = (lr: string, tail: string) => ({ params: { lr }, group_id: null, n: 0, mean: null, lo: null, hi: null, std: null, run_ids: [rid(tail)], runs: [{ run_id: rid(tail), status: "queued", seed: 1 }] });
    const summary = makeSummary(
      { cells: [cellRaw("1e-4", "a1"), cellRaw("3e-4", "c1")], best: null, headline: "No scored runs yet", total_usd: 0, counts: { queued: 2, running: 0, finished: 0, failed: 0, killed: 0, lost: 0, total: 2 }, run_ids: [rid("a1"), rid("c1")] },
      { task: null, grid: [{ name: "lr", values: ["1e-4", "3e-4"], low: null, high: null, log: false }], seeds: [1] },
    );
    const calls = mockApi(routes(summary, []));
    renderDetail();
    expect(await heading()).toBeTruthy();
    expect(screen.getByRole("region", { name: "Mean score per cell" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Mean score by lr" })).toBeTruthy();
    expect(screen.getByText("No scored runs yet", { selector: "p" })).toBeTruthy();
    await waitFor(() => expect(screen.getByText("No runs indexed yet")).toBeTruthy());
    expect(calls.some((call) => call.url.includes("/leaderboard"))).toBe(false);
  });

  test("an unknown sweep shows the server's error", async () => {
    mockApi({ [`GET /api/v1/sweeps/${PROJECT}/nope`]: new HttpReply(404, { error: "sweep not found: rxn/nope", type: "StoreError" }), "GET /api/v1/hosts": HOSTS });
    renderDetail("nope");
    expect((await screen.findByRole("alert")).textContent).toBe("sweep not found: rxn/nope");
    expect(screen.getByRole("heading", { level: 2, name: "nope" })).toBeTruthy();
  });

  test("Cancel queued refreshes the sweep", async () => {
    const calls = mockApi(routes());
    renderDetail();
    await heading();
    const gets = (): number => calls.filter((call) => call.method === "GET" && call.url === SWEEP).length;
    expect(gets()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel queued" }));
    await waitFor(() => expect(gets()).toBe(2));
    expect(calls.filter((call) => call.method === "POST").map((call) => call.url)).toEqual([`${SWEEP}/cancel_queued`]);
  });

  test("Add seeds while runs are still queued: new totals, Cancel covers them, later seeds next", async () => {
    let current = makeSummary();
    const added = ["a3", "b3", "c3", "d3", "a4", "b4", "c4", "d4"].map(rid);
    const extended = makeSummary(
      { counts: { queued: 9, running: 1, finished: 5, failed: 1, killed: 0, lost: 0, total: 16 }, run_ids: [...makeSummary().run_ids, ...added] },
      { seeds: [1, 2, 3, 4] },
    );
    const calls = mockApi({
      ...routes(),
      [`GET ${SWEEP}`]: () => current,
      [`POST ${SWEEP}/extend`]: () => {
        current = extended;
        return extended;
      },
    });
    renderDetail();
    await heading();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    await waitFor(() => expect(statValue("finished")).toBe("5 / 16"));
    expect(screen.getByRole("button", { name: "Cancel queued" }).getAttribute("title")).toBe("Cancel the 9 queued runs");
    expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({ seeds: [3, 4] });
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    expect(screen.getByText("5, 6 × 4 cells = 8 runs")).toBeTruthy();
  });

  test("a failed summary refetch keeps the sweep and an open Rerun dialog, and shows the error", async () => {
    const r: Record<string, unknown> = {
      ...routes(),
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      "GET /api/v1/runs?project=rxn&task=fwd&archived=true&limit=1000": RUNS,
      "GET /api/v1/projects": [{ project: PROJECT, repo: "/srv/code/rxn", description: "", tasks: [TASK] }],
    };
    mockApi(r);
    const { client } = renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Rerun sweep" }));
    for (let tick = 0; tick < 50; tick++) {
      await act(async () => {
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      });
      if (screen.queryByLabelText("Command") && (screen.queryByRole("radio", { name: "local" }) as HTMLInputElement | null)?.checked) break;
    }
    const dialog = screen.getByRole("dialog", { name: "Rerun sweep" });
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "D holds" } });
    r[`GET ${SWEEP}`] = new HttpReply(503, { error: "hub index locked", type: "IndexError" });
    await act(() => client.invalidateQueries({ queryKey: ["sweeps"] }));
    expect((await screen.findByRole("alert")).textContent).toBe("hub index locked");
    expect(screen.getByRole("heading", { level: 2, name: SWEEP_ID })).toBeTruthy();
    const open = screen.getByRole("dialog", { name: "Rerun sweep" });
    expect((within(open).getByLabelText("Hypothesis") as HTMLTextAreaElement).value).toBe("D holds");
    r[`GET ${SWEEP}`] = makeSummary();
    await act(() => client.invalidateQueries({ queryKey: ["sweeps"] }));
    await waitFor(() => expect(screen.queryByRole("alert") === null).toBe(true));
    expect((within(open).getByLabelText("Hypothesis") as HTMLTextAreaElement).value).toBe("D holds");
  });

  test("ages tick with the clock while the data stays the same", async () => {
    const ticks: (() => void)[] = [];
    const realSetInterval = globalThis.setInterval;
    globalThis.setInterval = ((fn: () => void, ms?: number, ...rest: unknown[]) => {
      if (ms === 30_000) ticks.push(fn);
      return realSetInterval(fn, ms, ...rest);
    }) as typeof setInterval;
    setSystemTime(new Date(NOW));
    try {
      mockApi(routes());
      renderWithClient(<SweepDetail project={PROJECT} sweepId={SWEEP_ID} />);
      const hosts = await screen.findByRole("region", { name: "Runs on hosts" });
      expect(await within(hosts).findByText("stale 4m")).toBeTruthy();
      setSystemTime(new Date(NOW + 10 * 60_000));
      act(() => {
        for (const tick of ticks) tick();
      });
      expect(await within(hosts).findByText("stale 14m")).toBeTruthy();
    } finally {
      setSystemTime();
      globalThis.setInterval = realSetInterval;
    }
  });

  test("zero-member issuance failure displays the recorded cause and resume guidance", async () => {
    const summary = {
      ...makeSummary(),
      counts: { total: 0 },
      run_ids: [],
      cells: [],
      best: null,
      issuance: {
        state: "incomplete" as const,
        episode: 1,
        revision: 3,
        planned: 8,
        accepted_at: "now",
        updated_at: "now",
        cancel_requested: false,
        reason: "launch_failed" as const,
        error: { type: "HostUnavailableError", message: "gpu1 disconnected" },
        resume: { seeds: [1, 2], message: "Reconnect gpu1, then resume" },
      },
    };
    mockApi(routes(summary, []));
    renderDetail();
    expect(await screen.findByText("Issuance incomplete · 0 observed / 8 planned")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("HostUnavailableError: gpu1 disconnected");
    expect(screen.getByRole("button", { name: "Resume" }).title).toBe("Reconnect gpu1, then resume");
  });
});
