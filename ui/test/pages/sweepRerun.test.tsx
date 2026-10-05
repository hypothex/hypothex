import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import type { RunRecord } from "../../src/api/models";
import { SEED_HISTORY_CUT } from "../../src/launch/draft";
import { parseCell, type SweepCellRow } from "../../src/pages/components/SweepModel";
import { rerunDefaults, SweepRerun } from "../../src/pages/components/SweepRerun";
import { SweepPage } from "../../src/pages/Sweep";
import { makeRecord } from "./fixtures";
import { type Call, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  CELL_B,
  CELL_D,
  HOSTS,
  NOW,
  PROJECT,
  RUNS,
  SWEEP_ID,
  TASK,
  TEMPLATE,
  makeSummary,
  makeSweepBoard,
  rid,
  run,
} from "./sweepFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const SWEEP = `/api/v1/sweeps/${PROJECT}/${SWEEP_ID}`;
const RUNS_URL = "/api/v1/runs?project=rxn&tag=sweep%3A0a1b2c3d%3As-7f3a&archived=true&limit=1000";
const REPO = "/Users/sv/code/rxn";
/** Every run of the sweep's task (the seed history): reruns launch with no sweep tag. */
const HISTORY_URL = "/api/v1/runs?project=rxn&task=fwd&archived=true&limit=1000";
const PROJECTS = [{ project: PROJECT, repo: REPO, description: "", tasks: [TASK] }];
/** A rerun of cell D's config outside the sweep (no sweep tag), with seed `seed`. */
const outside = (seed: number): RunRecord => ({
  ...run("d1"),
  run_id: `20261003-120000-fwd-r${seed}`,
  seed,
  tags: [],
  sweep_id: null,
});

describe("rerunDefaults", () => {
  test("the best cell's latest run: its template, params and vars, the next seeds, the sweep's host", () => {
    const spec = { ...makeSummary().spec, host: "gpu1" };
    const d = rerunDefaults(spec, parseCell(CELL_D), RUNS);
    expect(d.template?.run_id).toBe(rid("d1"));
    expect(d.initial).toEqual({
      command: "python train.py --lr {lr} --beam {beam} --seed {seed}",
      seeds: "3, 4, 5",
      host: "gpu1",
      gpus: 2,
    });
    expect(d.carry).toEqual({ params: { lr: "3e-4", beam: "10" }, vars: { lr: "3e-4", beam: "10" } });
    // the template ran clean: its commit is pinned; a dirty template pins nothing
    expect(d.commit).toBe("8f4cac43877b75953f18ff1daf7e6fc54a5d8f37");
    const dirty = RUNS.map((r) => (r.run_id === rid("d1") ? { ...r, git: { ...r.git, dirty: true } } : r));
    expect(rerunDefaults(spec, parseCell(CELL_D), dirty).commit).toBeNull();
  });

  test("seeds skip every run of the config, reruns outside the sweep too; a cut history proposes none", () => {
    const spec = makeSummary().spec;
    expect(rerunDefaults(spec, parseCell(CELL_D), RUNS, [outside(5)]).initial.seeds).toBe("6, 7, 8");
    const cut = rerunDefaults(spec, parseCell(CELL_D), RUNS, [outside(5)], false);
    expect([cut.initial.seeds, cut.seedsNote]).toEqual(["", SEED_HISTORY_CUT]);
  });

  test("a CPU template keeps 0 GPUs", () => {
    const cpu = RUNS.map((r) => ({ ...r, gpus_requested: 0 }));
    expect(rerunDefaults(makeSummary().spec, parseCell(CELL_D), cpu).initial.gpus).toBe(0);
  });

  test("no scored cell: the sweep's latest run; no runs: seeds 1, 2, 3 and nothing carried", () => {
    const late = { ...run("a1"), run_id: rid("z9"), created_at: "2026-10-03T11:00:00Z" };
    expect(rerunDefaults(makeSummary().spec, null, [...RUNS, late]).template?.run_id).toBe(rid("z9"));
    expect(rerunDefaults(makeSummary().spec, null, [])).toEqual({
      template: null,
      initial: { seeds: "1, 2, 3", host: null },
      carry: { params: {}, vars: {} },
      commit: null,
    });
  });
});

describe("Rerun sweep", () => {
  test("opens the Launch dialog from the best cell and launches its next seeds", async () => {
    const calls = mockApi({
      [`GET ${SWEEP}`]: makeSummary(),
      [`GET ${RUNS_URL}`]: RUNS,
      "GET /api/v1/hosts": HOSTS,
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      [`GET /api/v1/tasks/${PROJECT}/${TASK}/leaderboard`]: makeSweepBoard(),
      [`GET ${HISTORY_URL}`]: RUNS,
      "GET /api/v1/projects": PROJECTS,
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        return makeRecord({ run_id: `20261003-120000-fwd-r${seed}`, seed, status: "running" });
      },
    });
    renderWithClient(<SweepPage project={PROJECT} sweepId={SWEEP_ID} now={NOW} />);
    fireEvent.click(await screen.findByRole("button", { name: "Rerun sweep" }));

    const dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
    expect(within(dialog).getByText(`${PROJECT} / ${TASK}`)).toBeTruthy();
    expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe(TEMPLATE.join(" "));
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("3, 4, 5");
    await waitFor(() =>
      expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true),
    );
    // the template's commit is pinned and shown with the code location
    expect(within(dialog).getByText(`${REPO} @ 8f4cac4`)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), {
      target: { value: "best cell holds on new seeds" },
    });
    // The retained 2-GPU template cannot run on this CPU hub without an explicit edit.
    while (Number(within(dialog).getByLabelText("GPUs per run").textContent) > 0) {
      fireEvent.click(within(dialog).getByRole("button", { name: "Fewer GPUs per run" }));
    }
    fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));

    // the dialog's `<output>` (GPUs per run) is also a status role: wait for the dialog to
    // close. Poll a boolean: a failed `toBeNull()` on a DOM node prints the whole page tree
    await waitFor(() => expect(document.querySelector('[role="dialog"]') === null).toBe(true));
    const line = document.querySelector("p.launched");
    expect([line?.getAttribute("role"), line?.textContent]).toEqual(["status", "Launched 3 on local"]);
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([3, 4, 5]);
    expect(sent[0]?.body).toMatchObject({
      repo: REPO,
      task: TASK,
      command: TEMPLATE,
      params: { lr: "3e-4", beam: "10" },
      vars: { lr: "3e-4", beam: "10" },
      hypothesis: "best cell holds on new seeds",
      gpus: 0,
      queue: false,
      commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
    });
  });

  test("the defaults freeze when the dialog opens: a new best cell does not change what launches", async () => {
    const calls = mockApi({
      "GET /api/v1/hosts": HOSTS,
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      [`GET ${HISTORY_URL}`]: RUNS,
      "GET /api/v1/projects": PROJECTS,
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        return makeRecord({ run_id: `20261003-120000-fwd-r${seed}`, seed, status: "running" });
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spec = { ...makeSummary().spec, host: "local" };
    const launched: number[] = [];
    const tree = (best: SweepCellRow | null): ReactElement => (
      <QueryClientProvider client={client}>
        <SweepRerun
          project={PROJECT}
          spec={spec}
          best={best}
          runs={RUNS}
          onClose={() => {}}
          onLaunched={(records) => launched.push(records.length)}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(tree(parseCell(CELL_D)));
    const dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
    // a run finishes while the dialog is open and cell B becomes best
    rerender(tree(parseCell(CELL_B)));
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("3, 4, 5");
    fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: "D holds" } });
    await waitFor(() =>
      expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true),
    );
    // The retained 2-GPU template cannot run on this CPU hub without an explicit edit.
    while (Number(within(dialog).getByLabelText("GPUs per run").textContent) > 0) {
      fireEvent.click(within(dialog).getByRole("button", { name: "Fewer GPUs per run" }));
    }
    fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));
    await waitFor(() => expect(launched).toEqual([3]));
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([3, 4, 5]);
    for (const c of sent) {
      expect(c.body).toMatchObject({
        params: { lr: "3e-4", beam: "10" },
        vars: { lr: "3e-4", beam: "10" },
        commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
      });
    }
  });

  test("a second rerun proposes the seeds after the first one's, never the same seeds again", async () => {
    const started: RunRecord[] = [];
    const calls = mockApi({
      [`GET ${SWEEP}`]: makeSummary(),
      [`GET ${RUNS_URL}`]: RUNS,
      "GET /api/v1/hosts": HOSTS,
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      [`GET /api/v1/tasks/${PROJECT}/${TASK}/leaderboard`]: makeSweepBoard(),
      [`GET ${HISTORY_URL}`]: () => [...RUNS, ...started],
      "GET /api/v1/projects": PROJECTS,
      "POST /api/v1/runs": (call: Call) => {
        const seed = (call.body as { seed: number }).seed;
        const rec = { ...outside(seed), status: "running" as const };
        started.push(rec);
        return rec;
      },
    });
    renderWithClient(<SweepPage project={PROJECT} sweepId={SWEEP_ID} now={NOW} />);
    const launch = async (hypothesis: string): Promise<string> => {
      fireEvent.click(await screen.findByRole("button", { name: "Rerun sweep" }));
      const dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
      const seeds = (within(dialog).getByLabelText("Seeds") as HTMLInputElement).value;
      await waitFor(() =>
        expect((within(dialog).getByRole("radio", { name: "local" }) as HTMLInputElement).checked).toBe(true),
      );
      fireEvent.change(within(dialog).getByLabelText("Hypothesis"), { target: { value: hypothesis } });
      // The retained 2-GPU template cannot run on this CPU hub without an explicit edit.
    while (Number(within(dialog).getByLabelText("GPUs per run").textContent) > 0) {
      fireEvent.click(within(dialog).getByRole("button", { name: "Fewer GPUs per run" }));
    }
    fireEvent.click(within(dialog).getByRole("button", { name: "Launch 3" }));
      await waitFor(() => expect(document.querySelector('[role="dialog"]') === null).toBe(true));
      return seeds;
    };
    expect(await launch("first")).toBe("3, 4, 5");
    expect(await launch("second")).toBe("6, 7, 8");
    const sent = calls.filter((c) => c.method === "POST" && c.url === "/api/v1/runs");
    expect(sent.map((c) => (c.body as { seed: number }).seed)).toEqual([3, 4, 5, 6, 7, 8]);
  });

  test("reopened after runs started elsewhere, it reads the history again instead of its cache", async () => {
    const elsewhere: RunRecord[] = [];
    mockApi({
      [`GET ${SWEEP}`]: makeSummary(),
      [`GET ${RUNS_URL}`]: RUNS,
      "GET /api/v1/hosts": HOSTS,
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      [`GET /api/v1/tasks/${PROJECT}/${TASK}/leaderboard`]: makeSweepBoard(),
      [`GET ${HISTORY_URL}`]: () => [...RUNS, ...elsewhere],
      "GET /api/v1/projects": PROJECTS,
    });
    const { client } = renderWithClient(<SweepPage project={PROJECT} sweepId={SWEEP_ID} now={NOW} />);
    fireEvent.click(await screen.findByRole("button", { name: "Rerun sweep" }));
    let dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("3, 4, 5");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(document.querySelector('[role="dialog"]') === null).toBe(true));
    // an agent reruns the config while the dialog is closed; its run event marks runs stale
    elsewhere.push(outside(3), outside(4), outside(5));
    await act(() => client.invalidateQueries({ queryKey: ["runs"] }));
    fireEvent.click(screen.getByRole("button", { name: "Rerun sweep" }));
    dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("6, 7, 8");
  });

  test("opened before the sweep's runs arrive, it waits for them instead of freezing empty defaults", async () => {
    let release: (runs: RunRecord[]) => void = () => {};
    const late = new Promise<RunRecord[]>((resolve) => {
      release = resolve;
    });
    mockApi({
      [`GET ${SWEEP}`]: makeSummary(),
      [`GET ${RUNS_URL}`]: () => late,
      "GET /api/v1/hosts": HOSTS,
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
      [`GET /api/v1/tasks/${PROJECT}/${TASK}/leaderboard`]: makeSweepBoard(),
      [`GET ${HISTORY_URL}`]: RUNS,
      "GET /api/v1/projects": PROJECTS,
    });
    renderWithClient(<SweepPage project={PROJECT} sweepId={SWEEP_ID} now={NOW} />);
    fireEvent.click(await screen.findByRole("button", { name: "Rerun sweep" }));
    // the projects and the task history load, the sweep's runs do not: no dialog yet
    try {
      await new Promise((r) => setTimeout(r, 50));
      expect(screen.queryByRole("dialog", { name: "Rerun sweep" }) === null).toBe(true);
    } finally {
      release(RUNS);
    }
    const dialog = await screen.findByRole("dialog", { name: "Rerun sweep" });
    expect((within(dialog).getByLabelText("Command") as HTMLTextAreaElement).value).toBe(TEMPLATE.join(" "));
    expect((within(dialog).getByLabelText("Seeds") as HTMLInputElement).value).toBe("3, 4, 5");
  });
});
