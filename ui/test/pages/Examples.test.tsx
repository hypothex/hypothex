import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import type { PredictionPage, TaskDetail } from "../../src/pages/components/types";
import { ExamplesPage, pickExampleField } from "../../src/pages/Examples";
import { RUN_RF, RUN_SVM, makeDetail, makeDiff } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const PRED = `/api/v1/runs/${RUN_SVM}/predictions?metric=accuracy%40v1&failures_only=true&field=correct`;
const PROBE = `/api/v1/runs/${RUN_SVM}/predictions?metric=accuracy&limit=1`;
const COMPARE = `/api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=accuracy&field=correct`;

/** One predictions row whose per-example scores are `scores`. */
function probe(scores: Record<string, Record<string, unknown>>): PredictionPage {
  return { run_id: RUN_SVM, total: 180, offset: 0, limit: 1, rows: [{ id: "test-0", prediction: 1, reference: 1, scores }] };
}

function page(ids: [string, number, number][]): PredictionPage {
  return {
    run_id: RUN_SVM,
    total: 14,
    offset: 0,
    limit: ids.length,
    rows: ids.map(([id, prediction, reference]) => ({ id, prediction, reference, scores: {} })),
  };
}

function routes(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    [`GET /api/v1/runs/${RUN_RF}`]: makeDetail(
      { run_id: RUN_RF, hypothesis: "baseline rf", created_by: "human" },
      {
        scores: [
          {
            metric: "accuracy",
            version: "v1",
            key: "value",
            value: 0.8888888888888888,
            error: null,
            source_hash: null,
            created_at: "2026-09-26T21:00:33Z",
          },
        ],
      },
    ),
    [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(),
    [`GET ${PROBE}`]: probe({ "accuracy@v1": { correct: true } }),
    [`GET ${COMPARE}`]: makeDiff(),
    [`GET ${PRED}&limit=8`]: page([
      ["test-7", 2, 1],
      ["test-30", 2, 0],
    ]),
    [`GET ${PRED}&limit=58`]: page([
      ["test-7", 2, 1],
      ["test-30", 2, 0],
      ["test-54", 0, 2],
    ]),
    ...extra,
  };
}

test("compares two runs example by example", async () => {
  mockApi(routes());
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="accuracy" />);
  await screen.findByRole("heading", {
    level: 1,
    name: "RBF-kernel SVM fixes 9, breaks 3 vs baseline rf, p = 0.15",
  });
  for (const text of ["n = 180", "net +6", "Δ +0.0333", "baseline rf, seed 3", "RBF-kernel SVM, seed 3", "0.8889", "0.9222"]) {
    expect(screen.getByText(text)).toBeTruthy();
  }
  const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
  expect(names).toEqual(["a Outcomes", "b Sign test", "c Per example", "d RBF-kernel SVM errors"]);

  const errors = screen.getByRole("region", { name: "d RBF-kernel SVM errors" });
  const rows = await within(errors).findAllByRole("row");
  expect(rows.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
    [],
    ["test-7", "2", "1", "wrong"],
    ["test-30", "2", "0", "right"],
  ]);
  expect(errors.querySelector(".aside")?.textContent).toBe("2 of 14");
  fireEvent.click(within(errors).getByRole("button", { name: "+12 more" }));
  expect(await within(errors).findByText("test-54")).toBeTruthy();
  expect(errors.querySelector(".aside")?.textContent).toBe("3 of 14");
});

test("uses the task's primary metric when ?metric= is absent", async () => {
  const task: TaskDetail = {
    summary: {
      project: "toy-classifier",
      name: "toy-test",
      description: "",
      dataset: "toyset",
      dataset_version: "v1",
      split: "test",
      metrics: { accuracy: "v1", macro_f1: "v1" },
      primary: "accuracy/value",
      higher_is_better: true,
      n_runs: 12,
      best: 0.9222222222222222,
    },
    repo: "/private/tmp/hx-accept/toy",
    dataset: { name: "toyset" },
    metrics: {},
    stages: {},
  };
  const calls = mockApi(routes({ "GET /api/v1/tasks/toy-classifier/toy-test": task }));
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} />);
  await screen.findByRole("heading", { level: 1, name: /fixes 9, breaks 3/ });
  expect(calls.some((c) => c.url === COMPARE)).toBe(true);
});

test("shows the server error when a run has no per-example scores", async () => {
  mockApi(
    routes({
      [`GET ${COMPARE}`]: new HttpReply(400, {
        error: `run ${RUN_RF} has no per-example scores for accuracy@v1`,
        type: "EvalError",
      }),
    }),
  );
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="accuracy" />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    `run ${RUN_RF} has no per-example scores for accuracy@v1`,
  );
});

test("asks for ?metric= when run A has no task", async () => {
  mockApi(routes({ [`GET /api/v1/runs/${RUN_RF}`]: makeDetail({ run_id: RUN_RF, task: null }) }));
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} />);
  expect((await screen.findByRole("alert")).textContent).toBe("no task: add ?metric=<name> to the URL");
});

test("pickExampleField reads correct, then solved, then the first boolean field", () => {
  expect(pickExampleField(probe({ "accuracy@v1": { correct: false, loss: 0.2 } }), "accuracy")).toBe("correct");
  expect(pickExampleField(probe({ "solved@v2": { solved: 1, turns: 7 } }), "solved@v2")).toBe("solved");
  expect(pickExampleField(probe({ "rubric@v1": { score: 0.5, valid: true, exact: false } }), "rubric")).toBe("exact");
  expect(pickExampleField(probe({ "bleu@v1": { value: 31.2 } }), "bleu")).toBeUndefined();
  expect(pickExampleField(probe({}), "accuracy")).toBeUndefined();
  expect(pickExampleField(probe({ "other@v1": { correct: true } }), "accuracy")).toBeUndefined();
});

test("sends the solved field to compare and to the errors query", async () => {
  const solvedProbe = `/api/v1/runs/${RUN_SVM}/predictions?metric=solved&limit=1`;
  const solvedCompare = `/api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=solved&field=solved`;
  const solvedErrors = `/api/v1/runs/${RUN_SVM}/predictions?metric=solved%40v2&failures_only=true&field=solved&limit=8`;
  const calls = mockApi(
    routes({
      [`GET ${solvedProbe}`]: probe({ "solved@v2": { solved: false, turns: 12 } }),
      [`GET ${solvedCompare}`]: { ...makeDiff(), metric: "solved@v2", field: "solved" },
      [`GET ${solvedErrors}`]: page([["task-17", 0, 1]]),
    }),
  );
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="solved" />);
  await screen.findByRole("heading", { level: 1, name: /fixes 9, breaks 3/ });
  const errors = screen.getByRole("region", { name: "d RBF-kernel SVM errors" });
  expect(await within(errors).findByText("task-17")).toBeTruthy();
  const urls = calls.map((c) => c.url);
  expect(urls).toContain(solvedCompare);
  expect(urls).toContain(solvedErrors);
  expect(urls.some((u) => u.startsWith("/api/v1/compare/examples") && !u.includes("field="))).toBe(false);
});

test("comparison distinguishes two dirty patches at the same commit", async () => {
  const git = makeDetail().record.git;
  mockApi(routes({
    [`GET /api/v1/runs/${RUN_RF}`]: makeDetail({ run_id: RUN_RF, git: { ...git, dirty: true, diff_hash: "abcdef12" } }, { paths: { diff: "gpu1:/runs/a/git.diff" } }),
    [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail({ git: { ...git, dirty: true, diff_hash: "abcdef34" } }, { paths: { diff: "gpu2:/runs/b/git.diff" } }),
  }));
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="accuracy" />);
  expect(await screen.findByText(/dirty · patch abcdef12/)).toBeTruthy();
  expect(screen.getByText(/dirty · patch abcdef34/)).toBeTruthy();
  expect(screen.getByText("gpu2:/runs/b/git.diff")).toBeTruthy();
});

test("example comparison summary does not present a prior score after failed reevaluation", async () => {
  const detail = makeDetail();
  detail.scores.push({ metric: "accuracy", version: "v1", key: "*", value: null, error: "latest evaluation failed", source_hash: null, created_at: "2026-09-27T00:00:00Z" });
  mockApi(routes({ [`GET /api/v1/runs/${RUN_SVM}`]: detail }));
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="accuracy" />);
  await screen.findByRole("heading", { level: 1, name: /fixes 9/ });
  expect(screen.getByText("0.8889")).toBeTruthy();
  expect(screen.queryByText("0.9222") === null).toBe(true);
});

test("bare metric request uses the API-resolved version in comparison summaries", async () => {
  const detail = makeDetail();
  detail.scores.push({ metric: "accuracy", version: "v2", key: "value", value: 0.98, error: null, source_hash: null, created_at: "2026-09-27T00:00:00Z" });
  mockApi(routes({ [`GET /api/v1/runs/${RUN_SVM}`]: detail }));
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="accuracy" />);
  await screen.findByRole("heading", { level: 1, name: /fixes 9/ });
  expect(screen.getByText("0.9222")).toBeTruthy();
  expect(screen.queryByText("0.9800") === null).toBe(true);
});
