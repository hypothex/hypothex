import { afterEach, expect, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { Artifact, RunRecord, ScoreRecord } from "../../src/api/models";
import { CheckpointTable, TrainingCheckpoints, TrainingRuns, TRAINING_PAGE_SIZE } from "../../src/pages/components/TrainingDetails";
import { makeDetail, makeRecord } from "./fixtures";
import { mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(restoreFetch);
const checkpoint = (step: number | null, metrics: Record<string, number> = {}): Artifact => ({ kind: "checkpoint", step, metrics, path: `/ckpt/${step}.pt`, host: "gpu-a", size: null });
const score = (key: string, value: number | null, extra: Partial<ScoreRecord> = {}): ScoreRecord => ({ metric: "top1", version: "v2", key, value, error: null, source_hash: null, created_at: "2026-10-01T00:00:00Z", ...extra });
const listURL = "GET /api/v1/runs?project=p&task=t&limit=21";
const taskURL = "GET /api/v1/tasks/p/t";
const queryURL = "POST /api/v1/tasks/p/t/views/query";
const taskInfo = { summary: { metrics: { top1: "v2" } } };
function detailRoutes(runs: RunRecord[]) {
  return Object.fromEntries(runs.map(r => [`GET /api/v1/runs/${r.run_id}`, makeDetail(r, { scores: [], metric_names: ["train/loss", "val/top1", "sys/gpu_util", "sys/gpu_mem_gb"] })]));
}

test("checkpoint table keeps exact validation metrics, missing values, and path provenance", () => {
  renderWithClient(<CheckpointTable artifacts={[checkpoint(0, { "val/top1": 0, "val/loss": 1.5 }), checkpoint(20, { "val/loss": 0.75 }), { ...checkpoint(10), kind: "plot" }]} />);
  const table = screen.getByRole("table", { name: "Checkpoint metrics" });
  expect(within(table).getByRole("columnheader", { name: "val/top1" })).toBeTruthy();
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(table.textContent).toContain("gpu-a:/ckpt/0.pt");
  expect(table.textContent).not.toContain("/ckpt/10.pt");
  expect(table.textContent).not.toContain("test");
  expect(within(table).getAllByRole("row")[2]?.textContent).toContain("—");
});

test("killed and live runs retain checkpoints without fabricated evaluation scores", async () => {
  const killed = makeRecord({ run_id: "killed", status: "killed", seed: 0, artifacts: [checkpoint(20, { "val/top1": 0.8 }), checkpoint(10, { "val/top1": 0.9 })] });
  const live = makeRecord({ run_id: "live", status: "running", artifacts: [] });
  const selected: string[] = [];
  const calls = mockApi({ [listURL]: [killed, live], [taskURL]: taskInfo, ...detailRoutes([killed, live]), [queryURL]: { panels: [{ type: "curves", title: "Training observations", meta: {}, rows: [
    { run_id: "killed", name: "val/top1", step: 21, value: 0.99 },
    { run_id: "live", name: "train/loss", step: 42, value: 0.4 },
    { run_id: "live", name: "sys/gpu_util", step: 40, value: 0 },
    { run_id: "live", name: "sys/gpu_mem_gb", step: 40, value: 12.25 },
  ] }] } });
  renderWithClient(<TrainingRuns project="p" task="t" onSelectRun={id => selected.push(id)} />);
  await waitFor(() => expect(screen.getByRole("table", { name: "Training runs" }).textContent).toContain("12.25"));
  const rows = screen.getAllByRole("row");
  const killedCells = within(rows.find(r => r.textContent?.includes("killed"))!).getAllByRole("cell");
  expect(killedCells.map(c => c.textContent)).toEqual(["killed", "0", "killed", "21", "10", "—", "—", "—", "—", "mbp.local"]);
  fireEvent.click(screen.getByRole("link", { name: "live" }));
  expect(selected).toEqual(["live"]);
  const body = calls.find(c => c.method === "POST")?.body as { view: { panels: { data: { filter: unknown; max_points: number } }[] } };
  expect(body.view.panels[0]?.data.filter).toEqual({ run_id: ["killed", "live"] });
  expect(body.view.panels[0]?.data.max_points).toBe(2);
});

test("evaluated best and final use current version and latest record including errors", async () => {
  const record = makeRecord({ run_id: "r", artifacts: [checkpoint(2, { "val/top1": 0.99 })] });
  mockApi({ [listURL]: [record], [taskURL]: taskInfo, [queryURL]: { panels: [{ rows: [], meta: {} }] }, "GET /api/v1/runs/r": makeDetail(record, { scores: [score("value", 0.7), score("final", 0.6), score("value", 0.98, { version: "v1" }), score("final", null, { error: "failed evaluation", created_at: "2026-10-02T00:00:00Z" })] }) });
  renderWithClient(<TrainingRuns project="p" task="t" />);
  await waitFor(() => expect(screen.getByRole("table").textContent).toContain("0.7"));
  const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
  expect(cells[5]?.textContent).toBe("0.7");
  expect(cells[6]?.textContent).toBe("error");
  expect(screen.queryByText("0.98")).toBeNull();
});

test("checkpoint pages have bounded listing and preserve each run's attribution", async () => {
  const records = Array.from({ length: TRAINING_PAGE_SIZE + 1 }, (_, i) => makeRecord({ run_id: `r${i}`, artifacts: [checkpoint(i, { "val/top1": i })] }));
  const last = records[TRAINING_PAGE_SIZE - 1]!;
  const nextURL = `${listURL}&before_created_at=${encodeURIComponent(last.created_at)}&before_run_id=${last.run_id}`;
  const calls = mockApi({ [listURL]: records, [nextURL]: [records[TRAINING_PAGE_SIZE]] });
  renderWithClient(<TrainingCheckpoints project="p" task="t" />);
  await waitFor(() => expect(screen.getAllByRole("table")).toHaveLength(TRAINING_PAGE_SIZE));
  expect(screen.queryByRole("link", { name: "r20" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() => expect(screen.getByRole("link", { name: "r20" })).toBeTruthy());
  expect(calls).toHaveLength(2);
  expect(calls.every(c => c.url.startsWith("/api/v1/runs?"))).toBe(true);
});

test("training run page requests details only for twenty displayed records", async () => {
  const records = Array.from({ length: TRAINING_PAGE_SIZE + 1 }, (_, i) => makeRecord({ run_id: `bounded-${i}`, artifacts: [] }));
  const calls = mockApi({ [listURL]: records, [taskURL]: taskInfo, ...detailRoutes(records), [queryURL]: { panels: [{ rows: [], meta: {} }] } });
  renderWithClient(<TrainingRuns project="p" task="t" />);
  await waitFor(() => expect(calls.filter(c => /^\/api\/v1\/runs\/bounded-/.test(c.url))).toHaveLength(TRAINING_PAGE_SIZE));
  expect(calls.some(c => c.url === "/api/v1/runs/bounded-20")).toBe(false);
  await waitFor(() => expect(calls.filter(c => c.method === "POST")).toHaveLength(1));
});

test("failed next checkpoint page retains the previous-page control", async () => {
  const records = Array.from({ length: TRAINING_PAGE_SIZE + 1 }, (_, i) => makeRecord({ run_id: `page-${i}` }));
  mockApi({ [listURL]: records });
  renderWithClient(<TrainingCheckpoints project="p" task="t" />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Next page" }).hasAttribute("disabled")).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
  await screen.findByRole("link", { name: "page-0" });
});

test("metric request failure is unavailable rather than silently empty measurements", async () => {
  const record = makeRecord({ run_id: "r", artifacts: [] });
  mockApi({ [listURL]: [record], [taskURL]: taskInfo, ...detailRoutes([record]), [queryURL]: { panels: [{ rows: [], meta: { error: "remote read failed" } }] } });
  renderWithClient(<TrainingRuns project="p" task="t" />);
  await screen.findByText("Training observations could not be loaded.");
  const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
  expect(cells[3]?.textContent).toBe("unavailable");
  expect(cells[7]?.textContent).toBe("unavailable");
  expect(cells[8]?.textContent).toBe("unavailable");
});

test("checkpoint links preserve modifier navigation and empty checkpoints remain explicit", async () => {
  const selected: string[] = [];
  mockApi({ [listURL]: [makeRecord({ run_id: "empty", artifacts: [] })] });
  renderWithClient(<TrainingCheckpoints project="p" task="t" onSelectRun={id => selected.push(id)} />);
  const link = await screen.findByRole("link", { name: "empty" });
  expect(link.getAttribute("href")).toBe("/r/empty");
  fireEvent.click(link, { ctrlKey: true });
  expect(selected).toEqual([]);
  expect(screen.getByText("No checkpoints recorded.")).toBeTruthy();
});

for (const failedAt of ["2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"]) {
  test(`backend wildcard reevaluation failure at ${failedAt} supersedes both stored top1 keys`, async () => {
    const record = makeRecord({ run_id: "wildcard", artifacts: [] });
    mockApi({ [listURL]: [record], [taskURL]: taskInfo, [queryURL]: { panels: [{ rows: [], meta: {} }] }, "GET /api/v1/runs/wildcard": makeDetail(record, { scores: [score("value", 0.7), score("final", 0.6), score("*", null, { error: "Evaluator failed after prior success", created_at: failedAt })] }) });
    renderWithClient(<TrainingRuns project="p" task="t" />);
    await waitFor(() => expect(screen.getAllByTitle("Evaluator failed after prior success")).toHaveLength(2));
    const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
    expect(cells[5]?.textContent).toBe("error");
    expect(cells[6]?.textContent).toBe("error");
  });
}

test("successful reevaluation after wildcard failure recovers each key without version leakage", async () => {
  const record = makeRecord({ run_id: "recovered", artifacts: [] });
  mockApi({ [listURL]: [record], [taskURL]: taskInfo, [queryURL]: { panels: [{ rows: [], meta: {} }] }, "GET /api/v1/runs/recovered": makeDetail(record, { scores: [
    score("value", 0.7), score("final", 0.6),
    score("*", null, { error: "old failure", created_at: "2026-10-02T00:00:00Z" }),
    score("value", 0.8, { created_at: "2026-10-03T00:00:00Z" }),
    score("final", 0.75, { created_at: "2026-10-03T00:00:00Z" }),
    score("*", null, { version: "v1", error: "other version failure", created_at: "2026-10-04T00:00:00Z" }),
    score("*", null, { metric: "accuracy", error: "other metric failure", created_at: "2026-10-04T00:00:00Z" }),
  ] }) });
  renderWithClient(<TrainingRuns project="p" task="t" />);
  await screen.findByText("0.8");
  const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
  expect(cells[5]?.textContent).toBe("0.8");
  expect(cells[6]?.textContent).toBe("0.75");
});

test("history query names every discovered metric in bounded panels and retains last step from uncommon names", async () => {
  const record = makeRecord({ run_id: "many", artifacts: [] });
  const names = Array.from({ length: 205 }, (_, i) => `metric-${i}`);
  const calls = mockApi({ [listURL]: [record], [taskURL]: taskInfo, "GET /api/v1/runs/many": makeDetail(record, { scores: [], metric_names: names }), [queryURL]: { panels: [
    { rows: [{ run_id: "many", name: "metric-0", step: 12, value: 1 }], meta: {} },
    { rows: [], meta: {} },
    { rows: [{ run_id: "many", name: "metric-204", step: 999, value: 1 }], meta: {} },
  ] } });
  renderWithClient(<TrainingRuns project="p" task="t" />);
  await screen.findByText("999");
  const body = calls.find(call => call.method === "POST")?.body as { view: { panels: { data: { metrics: string[]; max_points: number; filter: unknown } }[] } };
  expect(body.view.panels.map(panel => panel.data.metrics.length)).toEqual([100, 100, 5]);
  expect(body.view.panels.flatMap(panel => panel.data.metrics)).toEqual(names);
  expect(body.view.panels.every(panel => panel.data.max_points === 2)).toBe(true);
  expect(body.view.panels.every(panel => JSON.stringify(panel.data.filter) === JSON.stringify({ run_id: ["many"] }))).toBe(true);
});

test("empty discovered metric names avoid an unrestricted history query", async () => {
  const record = makeRecord({ run_id: "empty-metrics", artifacts: [] });
  const calls = mockApi({ [listURL]: [record], [taskURL]: taskInfo, "GET /api/v1/runs/empty-metrics": makeDetail(record, { scores: [], metric_names: [] }) });
  renderWithClient(<TrainingRuns project="p" task="t" />);
  await waitFor(() => expect(screen.queryByLabelText("Loading evaluated score")).toBeNull());
  await screen.findByRole("link", { name: "empty-metrics" });
  expect(calls.some(call => call.method === "POST")).toBe(false);
  const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
  expect(cells[3]?.textContent).toBe("—");
});
