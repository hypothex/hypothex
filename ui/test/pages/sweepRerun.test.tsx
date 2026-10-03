import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { parseCell } from "../../src/pages/components/SweepModel";
import { rerunDefaults } from "../../src/pages/components/SweepRerun";
import { SweepPage } from "../../src/pages/Sweep";
import { makeRecord } from "./fixtures";
import { type Call, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
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
      "GET /api/v1/projects": [{ project: PROJECT, repo: REPO, description: "", tasks: [TASK] }],
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
});
