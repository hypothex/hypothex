import { afterEach, describe, expect, setSystemTime, test } from "bun:test";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { SweepPage, sweepRunsQuery } from "../../src/pages/Sweep";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  HOSTS,
  NOW,
  PROJECT,
  RUNS,
  SWEEP_ID,
  SWEEP_TAG,
  TASK,
  makeSummary,
  makeSweepBoard,
  rid,
} from "./sweepFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const SWEEP = `/api/v1/sweeps/${PROJECT}/${SWEEP_ID}`;
const RUNS_URL = "/api/v1/runs?project=rxn&tag=sweep%3A0a1b2c3d%3As-7f3a&archived=true&limit=1000";
const HEADLINE = "lr 3e-4, beam 10: 0.912 top1, +0.008 over beam 5";

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

function renderPage(sweepId = SWEEP_ID) {
  return renderWithClient(<SweepPage project={PROJECT} sweepId={sweepId} now={NOW} />);
}

describe("SweepPage", () => {
  test("sweepRunsQuery asks for every run with the sweep's member tag, archived included", () => {
    // no limit: useAllRuns pages through 1000, 4000, ... until a page is not full
    expect(sweepRunsQuery("rxn", SWEEP_TAG)).toEqual({
      project: "rxn",
      tag: "sweep:0a1b2c3d:s-7f3a",
      archived: true,
    });
  });

  test("headline, meta line, stats, progress and the three panels", async () => {
    mockApi(routes());
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: HEADLINE })).toBeTruthy();
    await waitFor(() => expect(statValue("best top1")).toBe("0.9120"));
    await waitFor(() => expect(statValue("cost, 11 GPU-h")).toBe("$12.50"));
    expect(statValue("95% CI")).toBe("0.908–0.916");
    expect(statValue("finished")).toBe("5 / 8");
    expect(statValue("ETA")).toBe("1h 30m");

    expect(screen.getByRole("link", { name: "rxn" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "fwd" }).getAttribute("href")).toBe("/t/rxn/fwd");
    expect(screen.getByText("sweep s-7f3a")).toBeTruthy();
    expect(screen.getByText("lr 2 × beam 2 × 2 seeds").parentElement?.textContent).toBe(
      "lr 2 × beam 2 × 2 seeds = 8",
    );
    // the hub's host names (matched by environment), not the runs' executor.host hostnames
    expect(await screen.findByText("gpu1, dgx")).toBeTruthy();
    for (const text of ["2 GPU / run", "agent:tuner", "09:12 UTC", "s-7f3a"]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
    expect(screen.getByRole("img", { name: "5 finished, 1 running, 1 queued, 1 failed" })).toBeTruthy();

    const a = screen.getByRole("region", { name: "a top1 by lr × beam" });
    expect(within(a).getByRole("table", { name: "Mean top1 by lr and beam" })).toBeTruthy();
    expect(within(a).getByRole("link", { name: "d1" }).getAttribute("href")).toBe(`/r/${rid("d1")}`);
    expect(screen.getByRole("region", { name: "b Seeds, 95% CI" })).toBeTruthy();
    const c = screen.getByRole("region", { name: "c Runs on hosts" });
    expect(await within(c).findByText("stale 4m")).toBeTruthy();
    expect(within(c).getByText("1 running, 1 queued")).toBeTruthy();
  });

  test("a one-param sweep without a task uses the table and asks for no leaderboard", async () => {
    const cellRaw = (lr: string, tail: string) => ({
      params: { lr },
      group_id: null,
      n: 0,
      mean: null,
      lo: null,
      hi: null,
      std: null,
      run_ids: [rid(tail)],
      runs: [{ run_id: rid(tail), status: "queued", seed: 1 }],
    });
    const summary = makeSummary(
      {
        cells: [cellRaw("1e-4", "a1"), cellRaw("3e-4", "c1")],
        best: null,
        headline: "No scored runs yet",
        total_usd: 0,
        counts: { queued: 2, running: 0, finished: 0, failed: 0, killed: 0, lost: 0, total: 2 },
        run_ids: [rid("a1"), rid("c1")],
      },
      {
        task: null,
        grid: [{ name: "lr", values: ["1e-4", "3e-4"], low: null, high: null, log: false }],
        seeds: [1],
      },
    );
    const calls = mockApi(routes(summary, []));
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "No scored runs yet" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "a score by lr" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Mean score by lr" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: TASK })).toBeNull();
    expect(screen.getByText("No scored runs yet", { selector: "p" })).toBeTruthy();
    await waitFor(() => expect(screen.getByText("No runs indexed yet")).toBeTruthy());
    expect(calls.some((call) => call.url.includes("/leaderboard"))).toBe(false);
  });

  test("an unknown sweep shows the server's error", async () => {
    mockApi({
      [`GET /api/v1/sweeps/${PROJECT}/nope`]: new HttpReply(404, {
        error: "sweep not found: rxn/nope",
        type: "StoreError",
      }),
      "GET /api/v1/hosts": HOSTS,
    });
    renderPage("nope");
    expect((await screen.findByRole("alert")).textContent).toBe("sweep not found: rxn/nope");
    expect(screen.getByText("sweep nope")).toBeTruthy();
  });

  test("Cancel queued refreshes the sweep", async () => {
    const calls = mockApi(routes());
    renderPage();
    await screen.findByRole("heading", { level: 1, name: HEADLINE });
    const gets = (): number => calls.filter((call) => call.method === "GET" && call.url === SWEEP).length;
    expect(gets()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel queued" }));
    await waitFor(() => expect(gets()).toBe(2));
    expect(calls.filter((call) => call.method === "POST").map((call) => call.url)).toEqual([
      `${SWEEP}/cancel_queued`,
    ]);
  });

  test("Add seeds while runs are still queued: new totals, Cancel covers them, later seeds next", async () => {
    let current = makeSummary();
    const added = ["a3", "b3", "c3", "d3", "a4", "b4", "c4", "d4"].map(rid);
    const extended = makeSummary(
      {
        counts: { queued: 9, running: 1, finished: 5, failed: 1, killed: 0, lost: 0, total: 16 },
        run_ids: [...makeSummary().run_ids, ...added],
      },
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
    renderPage();
    await screen.findByRole("heading", { level: 1, name: HEADLINE });
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    await waitFor(() => expect(statValue("finished")).toBe("5 / 16"));
    expect(screen.getByRole("button", { name: "Cancel queued" }).getAttribute("title")).toBe(
      "Cancel the 9 queued runs",
    );
    expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({ seeds: [3, 4] });
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    // 2 new seeds (the count stays 2) × 4 cells
    expect(screen.getByText("5, 6 × 4 cells = 8 runs")).toBeTruthy();
  });

  test("a failed summary refetch keeps the page and an open Rerun dialog, and shows the error", async () => {
    const r: Record<string, unknown> = {
      ...routes(),
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      "GET /api/v1/runs?project=rxn&task=fwd&archived=true&limit=1000": RUNS,
      "GET /api/v1/projects": [{ project: PROJECT, repo: "/Users/sv/code/rxn", description: "", tasks: [TASK] }],
    };
    mockApi(r);
    const { client } = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Rerun sweep" }));
    const dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "D holds" } });

    r[`GET ${SWEEP}`] = new HttpReply(503, { error: "hub index locked", type: "IndexError" });
    await act(() => client.invalidateQueries({ queryKey: ["sweeps"] }));
    expect((await screen.findByRole("alert")).textContent).toBe("hub index locked");
    expect(screen.getByRole("heading", { level: 1, name: HEADLINE })).toBeTruthy();
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
      renderWithClient(<SweepPage project={PROJECT} sweepId={SWEEP_ID} />);
      const c = await screen.findByRole("region", { name: "c Runs on hosts" });
      expect(await within(c).findByText("stale 4m")).toBeTruthy();
      setSystemTime(new Date(NOW + 10 * 60_000));
      act(() => {
        for (const tick of ticks) tick();
      });
      expect(await within(c).findByText("stale 14m")).toBeTruthy();
    } finally {
      setSystemTime();
      globalThis.setInterval = realSetInterval;
    }
  });
});
