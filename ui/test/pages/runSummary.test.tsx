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
