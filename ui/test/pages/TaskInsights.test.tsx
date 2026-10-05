import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test } from "bun:test";
import { cleanup, screen, within } from "@testing-library/react";
import { AgentIterationFlips, SystemRawSamples, repeatFlags, comparisonProblem } from "../../src/pages/components/TaskInsights";
import { makeBoard, makeDetail, makeDiff, RUN_RF, RUN_SVM } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => { cleanup(); restoreFetch(); });
const endpoint = "POST /api/v1/tasks/toy-classifier/toy-test/views/query";
function knownDetail(over: Parameters<typeof makeDetail>[0] = {}) {
  const detail = makeDetail(over);
  detail.scores = detail.scores.map(score => ({ ...score, source_hash: "source-v1", per_example_hash: "sha256:bound-artifact", evaluation_examples: 180, evaluation_ids_hash: "sha256:ids" }));
  return detail;
}
function routes() {
  return {
    [`GET /api/v1/runs/${RUN_RF}`]: knownDetail({ run_id: RUN_RF }),
    [`GET /api/v1/runs/${RUN_SVM}`]: knownDetail(),
    [`GET /api/v1/runs/${RUN_SVM}/predictions?metric=accuracy%40v1&limit=100`]: {
      run_id: RUN_SVM, total: 180, offset: 0, limit: 1,
      rows: [{ id: "1", scores: { "accuracy@v1": { correct: true } } }],
    },
    [`GET /api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=accuracy%40v1&field=correct&require_bound=true`]: makeDiff(),
  };
}
test("iteration flips use measured compatible examples and expose selectors", async () => {
  mockApi(routes());
  renderWithClient(<AgentIterationFlips project="toy-classifier" task="toy-test" board={makeBoard()} />);
  expect(await screen.findByText("9 fixed · 3 broken · 180 shared examples")).toBeTruthy();
  expect(screen.getByLabelText("Earlier version / group")).toBeTruthy();
  expect(screen.getByLabelText("Later version / group")).toBeTruthy();
  expect(screen.getByRole("img", { name: "Example outcomes: 9 fixed, 3 broken, 180 shared" })).toBeTruthy();
});
test("iteration flips reject mismatched dataset fingerprints before comparing", async () => {
  const detail = knownDetail(); detail.record.datasets[0]!.hash = "different";
  const calls = mockApi({ ...routes(), [`GET /api/v1/runs/${RUN_SVM}`]: detail });
  renderWithClient(<AgentIterationFlips project="toy-classifier" task="toy-test" board={makeBoard()} />);
  expect(await screen.findByText(/Incompatible comparison: dataset/)).toBeTruthy();
  expect(calls.some(c => c.url.includes("compare/examples"))).toBe(false);
});
test("iteration flips keep absent per-example data explicit", async () => {
  mockApi({ ...routes(), [`GET /api/v1/runs/${RUN_SVM}/predictions?metric=accuracy%40v1&limit=100`]: { rows: [] } });
  renderWithClient(<AgentIterationFlips project="toy-classifier" task="toy-test" board={makeBoard()} />);
  expect(await screen.findByText(/No binary per-example outcome/)).toBeTruthy();
});
test("raw samples are bounded, scoped in request, and disclose the actual total", async () => {
  const calls = mockApi({ [endpoint]: { panels: [{ type: "table", title: "Raw samples", rows: Array.from({ length: 140 }, (_, i) => ({ run_id: RUN_RF, name: "latency_ms", value: i, seed: 1 })), meta: { total: 9000, warnings: ["server capped response"] } }] } });
  renderWithClient(<SystemRawSamples project="toy-classifier" task="toy-test" selectedRunId={RUN_RF} />);
  expect(await screen.findByText("Showing 100 of 9000 samples.")).toBeTruthy();
  expect(within(screen.getByRole("table", { name: "Raw samples" })).getAllByRole("row")).toHaveLength(101);
  expect(calls[0]!.body).toMatchObject({ panel: { data: { source: "samples", filter: { run_id: RUN_RF } } } });
  expect(screen.getByText("server capped response")).toBeTruthy();
});
test("raw samples never infer the total from a bounded response", async () => {
  mockApi({ [endpoint]: { panels: [{ type: "table", rows: [{ run_id: RUN_RF, name: "latency_ms", value: 4 }], meta: {} }] } });
  renderWithClient(<SystemRawSamples project="toy-classifier" task="toy-test" />);
  expect(await screen.findByText("Showing 1 samples; total unknown.")).toBeTruthy();
});
test("repeat flags use measured p95 and complete fingerprinted population", () => {
  const rows = [100, 100, 121].map((value, i) => ({ run_id: `r${i}`, value, fingerprint: "latency@v1:sha1" }));
  const result = repeatFlags(rows, ["r0", "r1", "r2"]);
  expect(result.complete).toBe(true);
  expect(result.flags).toEqual([{ runId: "r2", relativeDelta: 0.21 }]);
  expect(repeatFlags(rows.slice(1), ["r0", "r1", "r2"]).complete).toBe(false);
  expect(repeatFlags(rows.map(r => ({ ...r, fingerprint: null })), ["r0", "r1", "r2"]).complete).toBe(false);
  expect(repeatFlags([...rows, rows[0]!], ["r0", "r1", "r2"]).complete).toBe(false);
});

 test("raw sample query errors remain errors, never an empty healthy table", async () => {
  mockApi({ [endpoint]: { panels: [{ type: "table", rows: [], meta: { error: "Samples are unavailable on this host" } }] } });
  renderWithClient(<SystemRawSamples project="toy-classifier" task="toy-test" />);
  expect((await screen.findByRole("alert")).textContent).toBe("Samples are unavailable on this host");
  expect(screen.queryByText("No raw samples returned.")).toBeNull();
});

test("comparison API failures do not render measured outcomes", async () => {
  mockApi({ ...routes(), [`GET /api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=accuracy%40v1&field=correct&require_bound=true`]: new HttpReply(422, { error: "No per-example scores", type: "EvalError" }) });
  renderWithClient(<AgentIterationFlips project="toy-classifier" task="toy-test" board={makeBoard()} />);
  expect((await screen.findByRole("alert")).textContent).toContain("No per-example scores");
  expect(screen.queryByRole("img")).toBeNull();
});
test("changing sample run hides stale rows until the newly scoped result arrives", async () => {
  let finish: ((value: unknown) => void) | undefined;
  mockApi({ [endpoint]: (call: { body: unknown }) => {
    const run = (call.body as {panel: {data: {filter: {run_id: string}}}}).panel.data.filter.run_id;
    if (run === RUN_RF) return { panels: [{ type: "table", rows: [{ run_id: RUN_RF, name: "old-series", value: 4 }], meta: { total: 1 } }] };
    return new Promise(resolve => { finish = resolve; });
  } });
  const rendered = renderWithClient(<SystemRawSamples project="toy-classifier" task="toy-test" selectedRunId={RUN_RF} />);
  await screen.findByText("old-series");
  rendered.rerender(<QueryClientProvider client={rendered.client}><SystemRawSamples project="toy-classifier" task="toy-test" selectedRunId={RUN_SVM} /></QueryClientProvider>);
  await screen.findByText("loading…");
  expect(screen.queryByText("old-series")).toBeNull();
  finish?.({ panels: [{ type: "table", rows: [{ run_id: RUN_SVM, name: "new-series", value: 8 }], meta: { total: 1 } }] });
  expect(await screen.findByText("new-series")).toBeTruthy();
});

test("unknown metric source hashes cannot establish a compatible population", () => {
  const a = makeDetail(); const b = makeDetail();
  for (const run of [a, b]) run.scores = run.scores.map(score => ({ ...score, source_hash: null }));
  expect(comparisonProblem(a, b, "accuracy@v1")).toContain("fingerprint");
});

test("an unscored first prediction does not hide later binary outcomes", async () => {
  mockApi({ ...routes(), [`GET /api/v1/runs/${RUN_SVM}/predictions?metric=accuracy%40v1&limit=100`]: {
    run_id: RUN_SVM, total: 180, offset: 0, limit: 100,
    rows: [{ id: "unscored", scores: {} }, { id: "scored", scores: { "accuracy@v1": { correct: true } } }],
  } });
  renderWithClient(<AgentIterationFlips project="toy-classifier" task="toy-test" board={makeBoard()} />);
  expect(await screen.findByText("9 fixed · 3 broken · 180 shared examples")).toBeTruthy();
});

test("a later wildcard failure blocks stale per-example comparison", () => {
  const a = knownDetail(); const b = knownDetail();
  b.scores.push({ metric: "accuracy", version: "v1", key: "*", value: null, error: "metric failed", source_hash: "source-v1", created_at: "2030-01-01T00:00:00Z" });
  expect(comparisonProblem(a, b, "accuracy@v1")).toContain("latest evaluation failed");
});

test("a successful later reevaluation replaces old failures and old source fingerprints", () => {
  const a = knownDetail(); const b = knownDetail();
  for (const run of [a, b]) {
    run.scores.push({ metric: "accuracy", version: "v1", key: "*", value: null, error: "metric failed", source_hash: "old-source", created_at: "2030-01-01T00:00:00Z" });
    run.scores.push({ metric: "accuracy", version: "v1", key: "value", value: 0.9, error: null, source_hash: "new-source", per_example_hash: "sha256:new-artifact", evaluation_examples: 180, evaluation_ids_hash: "sha256:ids", created_at: "2030-01-02T00:00:00Z" });
  }
  expect(comparisonProblem(a, b, "accuracy@v1")).toBeNull();
});

test("a mixed failure and numeric record in the same latest attempt remains failed", () => {
  const a = knownDetail(); const b = knownDetail();
  b.scores.push({ metric: "accuracy", version: "v1", key: "*", value: null, error: "partial metric failure", source_hash: "source-v1", created_at: "2030-01-01T00:00:00Z" }, { metric: "accuracy", version: "v1", key: "value", value: 0.9, error: null, source_hash: "source-v1", created_at: "2030-01-01T00:00:00Z" });
  expect(comparisonProblem(a, b, "accuracy@v1")).toContain("latest evaluation failed");
});

test("healthy aggregate-only reevaluation cannot reuse an older per-example artifact", async () => {
  const a = knownDetail({ run_id: RUN_RF }); const b = knownDetail();
  for (const run of [a, b]) {
    run.scores = run.scores.map(score => ({ ...score, per_example_hash: "sha256:old-artifact", evaluation_examples: 180, evaluation_ids_hash: "sha256:ids" }));
    run.scores.push({ metric: "accuracy", version: "v1", key: "value", value: 0.9, error: null, source_hash: "source-v1", per_example_hash: null, evaluation_examples: null, evaluation_ids_hash: null, created_at: "2030-01-02T00:00:00Z" });
  }
  const calls = mockApi({ ...routes(), [`GET /api/v1/runs/${RUN_RF}`]: a, [`GET /api/v1/runs/${RUN_SVM}`]: b });
  renderWithClient(<AgentIterationFlips project="toy-classifier" task="toy-test" board={makeBoard()} />);
  expect(await screen.findByText(/Incompatible comparison: latest evaluation has no bound per-example population/)).toBeTruthy();
  expect(calls.some(call => call.url.includes("/predictions?") || call.url.includes("/compare/examples?"))).toBe(false);
  expect(screen.queryByRole("img")).toBeNull();
});

test("server binding rejection never falls back to legacy comparison", async () => {
  const calls = mockApi({ ...routes(), [`GET /api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=accuracy%40v1&field=correct&require_bound=true`]: new HttpReply(400, { error: "Per-example artifact no longer matches its evaluation", type: "EvalError" }) });
  renderWithClient(<AgentIterationFlips project="toy-classifier" task="toy-test" board={makeBoard()} />);
  expect((await screen.findByRole("alert")).textContent).toContain("no longer matches");
  expect(screen.queryByRole("img")).toBeNull();
  expect(calls.filter(call => call.url.includes("compare/examples")).map(call => call.url)).toEqual([
    `/api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=accuracy%40v1&field=correct&require_bound=true`,
  ]);
});

test("latest per-example binding requires positive population counts and consistent output keys", () => {
  for (const count of [undefined, null, 0, -1, 1.5, Number.POSITIVE_INFINITY]) {
    const a = knownDetail(); const b = knownDetail();
    b.scores = b.scores.map(score => ({ ...score, evaluation_examples: count }));
    expect(comparisonProblem(a, b, "accuracy@v1")).toContain("no bound per-example population");
  }
  const a = knownDetail(); const b = knownDetail();
  const score = b.scores.find(row => row.metric === "accuracy")!;
  b.scores.push({ ...score, key: "another", per_example_hash: "sha256:different-artifact" });
  expect(comparisonProblem(a, b, "accuracy@v1")).toContain("conflicting per-example bindings");
});
