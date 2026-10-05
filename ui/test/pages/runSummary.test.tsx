import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { runStats } from "../../src/pages/components/runStats";
import {
  ScoresList,
  latestScores,
  primaryRef,
  scoreFor,
  scoreLabel,
} from "../../src/pages/components/ScoresList";
import { StatusLine } from "../../src/pages/components/StatusLine";
import type { ScoreRecord } from "../../src/pages/components/types";
import { RUN_RF, makeBoard, makeDetail, makeRecord } from "./fixtures";

afterEach(cleanup);

function score(over: Partial<ScoreRecord>): ScoreRecord {
  return {
    metric: "accuracy",
    version: "v1",
    key: "value",
    value: 0.5,
    error: null,
    source_hash: null,
    created_at: "2026-09-26T21:00:00Z",
    ...over,
  };
}

describe("scores", () => {
  const scores = [
    score({ value: 0.9, created_at: "2026-09-26T21:00:00Z" }),
    score({ value: 0.92, created_at: "2026-09-26T22:00:00Z" }),
    score({ metric: "macro_f1", value: 0.91 }),
    score({ version: "v0", value: 0.7 }),
    score({ key: "top5", value: 0.99 }),
    score({ metric: "bleu", value: null, error: "division by zero" }),
  ];

  test("latestScores keeps the newest per metric, version, key (sorted by key: top5 < value)", () => {
    expect(latestScores(scores).map((s) => [scoreLabel(s), s.value])).toEqual([
      ["accuracy v0", 0.7],
      ["accuracy v1/top5", 0.99],
      ["accuracy v1", 0.92],
      ["bleu v1", null],
      ["macro_f1 v1", 0.91],
    ]);
  });

  test("scoreFor resolves name, name@version, and name@version/key", () => {
    expect(scoreFor(scores, "accuracy@v1")).toBe(0.92);
    expect(scoreFor(scores, "accuracy@v1/top5")).toBe(0.99);
    expect(scoreFor(scores, "accuracy@v0/value")).toBe(0.7);
    expect(scoreFor(scores, "macro_f1")).toBe(0.91);
    expect(scoreFor(scores, "bleu@v1")).toBeNull();
    expect(scoreFor(scores, "missing")).toBeNull();
  });

  test("ScoresList shows values, the primary interval, errors, and logged metrics", () => {
    const board = makeBoard();
    render(
      <ScoresList
        scores={[...makeDetail().scores, score({ metric: "bleu", error: "division by zero", value: null })]}
        metricNames={["train_accuracy"]}
        primary={primaryRef(board, board.rows[0] ?? null)}
      />,
    );
    expect(screen.getByText("0.9222")).toBeTruthy();
    expect(screen.getByText("0.9225")).toBeTruthy();
    expect(screen.getByText("0.874–0.953")).toBeTruthy();
    expect(screen.getByText("21:03 · e662a37b")).toBeTruthy();
    expect(screen.getByText("error").getAttribute("title")).toBe("division by zero");
    expect(screen.getByText("logged: train_accuracy")).toBeTruthy();
  });
});

describe("runStats", () => {
  test("primary score, interval, seeds, wall time", () => {
    const board = makeBoard();
    const row = board.rows[0] ?? null;
    const stats = runStats(makeDetail(), primaryRef(board, row), row);
    expect(stats.map((s) => [s.label, s.value])).toEqual([
      ["accuracy v1", "0.9222"],
      ["95% CI", "0.874–0.953"],
      ["seeds", "◇×3"],
      ["wall", "0.8 s"],
    ]);
  });

  test("the board's unit: suffix units go in the unit field, $ leads the value", () => {
    const board = { ...makeBoard(), unit: "ms", value_format: "percent_delta" };
    const row = board.rows[0] ?? null;
    const primary = primaryRef(board, row);
    expect(primary?.unit).toBe("ms");
    const [first] = runStats(makeDetail(), primary, row);
    expect([first?.value, first?.unit]).toEqual(["0.922", "ms"]);
    const usd = runStats(makeDetail(), primaryRef({ ...board, unit: "$", value_format: "number" }, row), row)[0];
    expect([usd?.value, usd?.unit]).toEqual(["$0.922", null]);
  });

  test("usage and a failing exit code; no board means no score stats", () => {
    const detail = makeDetail({
      status: "failed",
      exit_code: 2,
      usage: { tokens_in: 153000, tokens_out: 4500, usd: 0.25, seconds: 68.4, calls: 13 },
    });
    expect(runStats(detail, null, null).map((s) => [s.label, s.value])).toEqual([
      ["wall", "0.8 s"],
      ["tokens in", "153k"],
      ["tokens out", "4.5k"],
      ["cost", "$0.25"],
      ["exit", "2"],
    ]);
  });
});

test("StatusLine lists status, time, launcher, host, tags, and parent", () => {
  render(<StatusLine record={makeRecord({ kind: "infer", parent: RUN_RF })} />);
  for (const text of ["finished", "0.8 s", "seed 3", "21:03:06 UTC", "agent:acceptance", "mbp.local", "infer", "best", "svm"]) {
    expect(screen.getByText(text)).toBeTruthy();
  }
  expect(screen.getByRole("link", { name: "parent ef4f" }).getAttribute("href")).toBe(`/r/${RUN_RF}`);
});

for (const failedAt of ["2026-09-26T21:00:00Z", "2026-09-26T22:00:00Z"]) {
  test(`scoreFor rejects an equal/newer backend wildcard error at ${failedAt}`, () => {
    const records = [score({ value: 0.8 }), score({ key: "top5", value: 0.9 }), score({ key: "*", value: null, error: "reevaluation failed", created_at: failedAt })];
    expect(scoreFor(records, "accuracy@v1")).toBeNull();
    expect(scoreFor(records, "accuracy@v1/top5")).toBeNull();
    expect(scoreFor(records, "accuracy")).toBeNull();
  });
}

test("scoreFor rejects mixed value/error attempts and recovers after a later successful retry", () => {
  const records = [
    score({ key: "*", value: null, error: "partially failed evaluator", created_at: "2026-09-26T22:00:00Z" }),
    score({ value: 0.8, created_at: "2026-09-26T22:00:00Z" }),
  ];
  expect(scoreFor(records, "accuracy@v1/value")).toBeNull();
  records.push(score({ value: 0.85, created_at: "2026-09-26T23:00:00Z" }));
  expect(scoreFor(records, "accuracy@v1/value")).toBe(0.85);
  records.push(score({ version: "v0", key: "*", value: null, error: "another version", created_at: "2026-09-27T00:00:00Z" }));
  records.push(score({ metric: "other", key: "*", value: null, error: "another metric", created_at: "2026-09-27T00:00:00Z" }));
  expect(scoreFor(records, "accuracy@v1/value")).toBe(0.85);
});

test("scoreFor never replaces a failed preferred value with another field", () => {
  const records = [score({ key: "top5", value: 0.95 }), score({ value: null, error: "value failed", created_at: "2026-09-26T22:00:00Z" })];
  expect(scoreFor(records, "accuracy@v1")).toBeNull();
  expect(scoreFor(records, "accuracy@v1/top5")).toBe(0.95);
});

test("score summaries hide failed reevaluation while ScoresList retains timestamped records", () => {
  const detail = makeDetail({}, { scores: [score({ value: 0.8 }), score({ key: "*", value: null, error: "reevaluation failed", created_at: "2026-09-26T22:00:00Z" })] });
  const primary = { metric: "accuracy", version: "v1", key: "value", interval: null };
  expect(runStats(detail, primary, null).some(item => item.label === "accuracy v1")).toBe(false);
  render(<ScoresList scores={detail.scores} metricNames={[]} primary={primary} />);
  expect(screen.getByText("0.8000")).toBeTruthy();
  expect(screen.getByText("error").getAttribute("title")).toBe("reevaluation failed");
  expect(screen.getByText("21:00")).toBeTruthy();
  expect(screen.getByText("22:00")).toBeTruthy();
});

test("runStats suppresses a cached primary interval after that run's reevaluation fails", () => {
  const board = makeBoard();
  const row = board.rows[0]!;
  const detail = makeDetail();
  detail.scores.push(score({ key: "*", value: null, error: "reevaluation failed", created_at: "2026-09-27T00:00:00Z" }));
  const primary = primaryRef(board, row);
  expect(primary?.interval).not.toBeNull();
  const labels = runStats(detail, primary, row).map(item => item.label);
  expect(labels.includes("accuracy v1")).toBe(false);
  expect(labels.includes("95% CI")).toBe(false);
});
