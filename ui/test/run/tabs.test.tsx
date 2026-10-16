import { afterEach, expect, test } from "bun:test";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { ChartsTab } from "../../src/run/ChartsTab";
import { ExamplesTab } from "../../src/run/ExamplesTab";
import { FilesTab } from "../../src/run/FilesTab";
import { LogsTab } from "../../src/run/LogsTab";
import { RUN_RF, RUN_SVM, makeDetail } from "../pages/fixtures";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { makeCtx } from "./ctx";
import { SVM_SIBLINGS } from "./taskRunsFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

test("Charts: one section per metric prefix, one request per run for all shown names", async () => {
  const names = ["train/loss", "train/acc", "val/top1", "lr", "sweep/p95"];
  const q = "names=train%2Floss&names=train%2Facc&names=val%2Ftop1&names=lr&max_points=300";
  const routes = Object.fromEntries([RUN_SVM, ...SVM_SIBLINGS].map((id) => [`GET /api/v1/runs/${id}/metrics?${q}`, []]));
  const calls = mockApi(routes);
  renderWithClient(<ChartsTab ctx={makeCtx({}, makeDetail({}, { metric_names: names }))} />);
  for (const title of ["train", "val", "metrics"]) expect(screen.getByText(title)).toBeTruthy();
  for (const metric of ["train/loss", "train/acc", "val/top1", "lr"]) expect(screen.getByText(metric)).toBeTruthy();
  expect(screen.queryByText("sweep/p95")).toBeNull();
  await waitFor(() => expect(calls).toHaveLength(3));
  expect(screen.getByText("This run in colour, the other seeds of its config in grey.")).toBeTruthy();
});

test("Charts with no step metrics says so", () => {
  mockApi({});
  renderWithClient(<ChartsTab ctx={makeCtx({}, makeDetail({}, { metric_names: [] }))} />);
  expect(screen.getByText("No step metrics logged")).toBeTruthy();
});

test("Files: command and template, git line, code, every run file, data, checkpoints for training", () => {
  mockApi({});
  const ctx = makeCtx({ kind: { kind: "training", run_view: [] } });
  renderWithClient(<FilesTab ctx={ctx} />);
  expect(screen.getByText("python train_eval.py --model svm --seed=3")).toBeTruthy();
  expect(screen.getByText("python train_eval.py --model svm --seed={seed}")).toBeTruthy();
  expect(screen.getByText("main @ 8f4cac4")).toBeTruthy();
  const files = screen.getByRole("region", { name: "Run files" });
  expect([...files.querySelectorAll(".fname")].map((f) => f.textContent)).toContain("env");
  expect(within(screen.getByRole("region", { name: "Data" })).getByText("toyset v1 test")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "Code" })).getByText("Project")).toBeTruthy();
  expect(screen.getByRole("table", { name: "Checkpoint metrics" })).toBeTruthy();
});

test("Files: no checkpoints section for a non-training run", () => {
  mockApi({});
  renderWithClient(<FilesTab ctx={makeCtx()} />);
  expect(screen.queryByRole("region", { name: "Checkpoints" })).toBeNull();
});

test("Logs: the ?log= stream (default stdout) with links to the others", async () => {
  mockApi({
    [`GET /api/v1/runs/${RUN_SVM}/logs?stream=stderr`]: { stream: "stderr", text: "Traceback: boom\n", offset: 15, size: 15 },
  });
  renderWithClient(<LogsTab ctx={makeCtx({ log: "stderr" })} />);
  expect(await screen.findByText("Traceback: boom")).toBeTruthy();
  expect(screen.getByText("15 B")).toBeTruthy();
  const nav = screen.getByRole("navigation", { name: "Log stream" });
  expect(within(nav).getByRole("link", { name: "stdout" }).getAttribute("href")).toBe(`/r/${RUN_SVM}?tab=logs&log=stdout`);
  expect(within(nav).getByRole("link", { name: "stderr" }).getAttribute("aria-current")).toBe("true");
});

test("Logs without ?log= shows stdout", async () => {
  mockApi({
    [`GET /api/v1/runs/${RUN_SVM}/logs?stream=stdout`]: { stream: "stdout", text: "epoch 1\n", offset: 8, size: 8 },
  });
  renderWithClient(<LogsTab ctx={makeCtx()} />);
  expect(await screen.findByText("epoch 1")).toBeTruthy();
  const nav = screen.getByRole("navigation", { name: "Log stream" });
  expect(within(nav).getByRole("link", { name: "stdout" }).getAttribute("aria-current")).toBe("true");
});

test("Examples: other configs with their score, each opening the Examples page", () => {
  mockApi({});
  renderWithClient(<ExamplesTab ctx={makeCtx()} />);
  const row = screen.getByRole("row", { name: /model rf/ });
  expect(within(row).getByText("0.8852")).toBeTruthy();
  expect(within(row).getByRole("link", { name: "Open" }).getAttribute("href")).toBe(`/x/${RUN_RF}/${RUN_SVM}`);
});

test("Examples for a run without a task explains why there is nothing to compare", () => {
  mockApi({});
  renderWithClient(<ExamplesTab ctx={makeCtx({ taskRuns: null }, makeDetail({ task: null }), null)} />);
  expect(screen.getByText("Examples compare runs of one task; this run has no task.")).toBeTruthy();
});
