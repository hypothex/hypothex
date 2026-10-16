import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ScoreRecord } from "../../src/api/models";
import { OverviewTab } from "../../src/run/OverviewTab";
import { RUN_SVM, makeDetail } from "../pages/fixtures";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { GPU1, QUEUED_ID, queuedRecord, remoteDetail } from "../pages/remoteFixtures";
import { makeCtx } from "./ctx";
import { SVM_SIBLINGS } from "./taskRunsFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const metrics = (id: string) => `GET /api/v1/runs/${id}/metrics?names=train_accuracy&max_points=300`;
const curves = () => ({
  [metrics(RUN_SVM)]: [{ name: "train_accuracy", step: 0, value: 0.9, t: null }],
  [metrics(SVM_SIBLINGS[0])]: [],
  [metrics(SVM_SIBLINGS[1])]: [],
});

test("Scores: tiles with the primary first, Δ vs config mean, and where the run ranks", async () => {
  mockApi(curves());
  renderWithClient(<OverviewTab ctx={makeCtx()} />);
  const scores = screen.getByRole("region", { name: "Scores" });
  const tiles = [...scores.querySelectorAll(".tile")];
  expect(tiles.map((t) => t.querySelector(".tl")?.textContent)).toEqual(["accuracy@v1", "macro_f1@v1"]);
  expect(tiles[0]?.querySelector(".star")?.textContent).toBe("primary");
  expect(tiles[0]?.querySelector(".tv")?.textContent).toBe("0.9222");
  expect(tiles[0]?.querySelector(".td .delta-up")?.textContent).toBe("+0.0248");
  expect(tiles[0]?.querySelector(".td")?.getAttribute("title")).toBe("outside 1 sd (0.0221) of the config's seeds");
  expect(tiles[1]?.querySelector(".td .muted")?.textContent).toBe("+0.0007");
  expect(within(scores).getByText("Where it ranks")).toBeTruthy();
  expect(within(scores).getByText("accuracy@v1 · 1st of 3 seeds · config is best of 2")).toBeTruthy();
  expect([...scores.querySelectorAll(".rank-legend span")].map((s) => s.textContent)).toEqual([
    "this run", "other seeds", "other configs", "best config, 95% CI",
  ]);
});

test("more than eight scores: eight tiles and a button for the rest", () => {
  mockApi(curves());
  const many: ScoreRecord[] = Array.from({ length: 12 }, (_, i) => ({
    metric: "reported", version: "v1", key: `ds${i}.model-x.top10`, value: i / 10, error: null, source_hash: null, created_at: "2026-09-26T21:03:08Z",
  }));
  renderWithClient(<OverviewTab ctx={makeCtx({}, makeDetail({}, { scores: many }))} />);
  expect(document.querySelectorAll(".tile")).toHaveLength(8);
  fireEvent.click(screen.getByRole("button", { name: "All 12 scores" }));
  expect(document.querySelectorAll(".tile")).toHaveLength(12);
});

test("Curves: this run and its seeds are read with the shown names; All charts opens Charts", async () => {
  const calls = mockApi(curves());
  renderWithClient(<OverviewTab ctx={makeCtx()} />);
  const section = screen.getByRole("region", { name: "Curves" });
  expect(within(section).getByRole("link", { name: "All charts" }).getAttribute("href")).toBe(`/r/${RUN_SVM}?tab=charts`);
  await waitFor(() => expect(calls.map((c) => c.url).sort()).toEqual(Object.keys(curves()).map((k) => k.slice(4)).sort()));
  expect(within(section).getByText("train_accuracy")).toBeTruthy();
});

test("Files: rows with sizes, a link to the log tab and a copy button per row", () => {
  mockApi(curves());
  renderWithClient(<OverviewTab ctx={makeCtx()} />);
  const files = screen.getByRole("region", { name: "Files" });
  expect(within(files).getByText("on mbp.local")).toBeTruthy();
  expect([...files.querySelectorAll(".file .fname")].map((f) => f.textContent)).toEqual([
    "Run folder", "stdout.log", "stderr.log", "predictions", "model.pkl",
  ]);
  expect(files.querySelector(".file:last-child small")?.textContent).toBe("checkpoint");
  expect(within(files).getByRole("link", { name: "stderr.log" }).getAttribute("href")).toBe(`/r/${RUN_SVM}?tab=logs&log=stderr`);
  expect(within(files).getByText("18.5 KB")).toBeTruthy();
  expect(within(files).getAllByRole("button", { name: /^Copy / })).toHaveLength(5);
});

test("a queued remote run shows its host queue and no scores", async () => {
  const QUEUE = `GET /api/v1/runs?status=queued&environment_id=env-gpu1&limit=1000`;
  mockApi({ [QUEUE]: [queuedRecord()] });
  const detail = remoteDetail(queuedRecord());
  renderWithClient(<OverviewTab ctx={makeCtx({ phase: "queued", host: GPU1, hostsLoaded: true, remote: true, taskRuns: null }, detail, null)} />);
  const queue = screen.getByRole("region", { name: "Queue" });
  expect(within(queue).getByText(`gpu1, ${GPU1.queue} waiting`)).toBeTruthy();
  await waitFor(() => expect(queue.querySelectorAll(".queue-t tbody tr")).toHaveLength(1));
  expect(queue.querySelector(".queue-t tr.me")?.textContent).toContain(QUEUED_ID.split("-").pop() ?? "");
  expect(screen.queryByRole("region", { name: "Scores" })).toBeNull();
  expect(screen.queryByRole("region", { name: "Curves" })).toBeNull();
});
