import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MINUS } from "../../src/charts/Scale";
import type { PanelResult } from "../../src/panels/index";
import {
  Leaderboard,
  bestBand,
  examplesHref,
  fmtDuration,
  metricLabel,
  primaryKey,
  verdictOf,
  type LeaderboardRowJson,
} from "../../src/panels/Leaderboard";

afterEach(cleanup);

/*
 * Fixture mirrors docs/mockups/ui-v4 (toy-test, n = 180 test examples).
 * Seed scores are k/180: SVM 166/180 on all three seeds; rf 158, 160, 160;
 * knn 156 on all seeds; logreg 149 on all seeds.
 * rf mean = (0.877778 + 0.888889 + 0.888889) / 3 = 0.885185,
 * rf sample std = sqrt(((-0.007407)^2 + 2 * 0.003704^2) / 2) = 0.006415.
 * Wilson 95% intervals (z = 1.959964) as drawn in the mockup.
 */
function row(over: Partial<LeaderboardRowJson> & Pick<LeaderboardRowJson, "group_id">): LeaderboardRowJson {
  return {
    run_ids: ["r1", "r2", "r3"],
    latest_run_id: "r3",
    hypothesis: "h",
    commit: "2bbf5a3",
    n: 3,
    scores: {},
    primary: null,
    single_seed: false,
    label: over.group_id,
    seed_values: {},
    identical_seeds: false,
    test_interval: null,
    vs_best: null,
    created_by: ["human"],
    usage: null,
    ...over,
  };
}
const stat = (mean: number, std = 0, n = 3) => ({ mean, std, n, ci_low: null, ci_high: null });
const SVM = row({
  group_id: "6f71aa00@8f4cac4",
  latest_run_id: "20260926-6f71",
  hypothesis: "RBF-kernel SVM beats the tree baselines",
  label: "RBF-kernel SVM",
  scores: { "accuracy/value": stat(0.922222), "macro_f1/value": stat(0.9225) },
  primary: stat(0.922222),
  seed_values: { "accuracy/value": [0.922222, 0.922222, 0.922222] },
  identical_seeds: true,
  test_interval: { lo: 0.874, hi: 0.953, method: "wilson", n: 180 },
  created_by: ["agent:acceptance"],
});
const RF = row({
  group_id: "ef4f0000@2bbf5a3",
  label: "Baseline rf",
  scores: { "accuracy/value": stat(0.885185, 0.006415), "macro_f1/value": stat(0.8855, 0.006) },
  primary: stat(0.885185, 0.006415),
  seed_values: { "accuracy/value": [0.877778, 0.888889, 0.888889] },
  test_interval: { lo: 0.83, hi: 0.924, method: "wilson", n: 180 },
  vs_best: { delta: -0.037037, p: 0.146, fixed: 9, broken: 3, test: "sign", examples_needed: 250 },
});
const KNN = row({
  group_id: "3f7e0000@2bbf5a3",
  label: "Baseline knn",
  scores: { "accuracy/value": stat(0.866667), "macro_f1/value": stat(0.8664) },
  primary: stat(0.866667),
  seed_values: { "accuracy/value": [0.866667, 0.866667, 0.866667] },
  identical_seeds: true,
  test_interval: { lo: 0.809, hi: 0.909, method: "wilson", n: 180 },
  vs_best: { delta: -0.055556, p: null, fixed: null, broken: null, test: null, examples_needed: null },
});
const LOGREG = row({
  group_id: "a50e0000@2bbf5a3",
  label: "Baseline logreg",
  scores: { "accuracy/value": stat(0.827778), "macro_f1/value": stat(0.8291) },
  primary: stat(0.827778),
  seed_values: { "accuracy/value": [0.827778, 0.827778, 0.827778] },
  identical_seeds: true,
  test_interval: { lo: 0.766, hi: 0.876, method: "wilson", n: 180 },
  vs_best: { delta: -0.094444, p: null, fixed: null, broken: null, test: null, examples_needed: null },
});
const ROWS = [SVM, RF, KNN, LOGREG];
const board = (meta: Record<string, unknown> = {}, rows = ROWS): PanelResult => ({
  type: "leaderboard",
  title: "All ideas",
  rows: rows as unknown as Array<Record<string, unknown>>,
  meta,
});

describe("helpers", () => {
  test("primaryKey: meta hint, bare metric name, or matching stats", () => {
    expect(primaryKey(ROWS, {})).toBe("accuracy/value");
    expect(primaryKey(ROWS, { primary: "macro_f1/value" })).toBe("macro_f1/value");
    expect(primaryKey(ROWS, { primary: "accuracy" })).toBe("accuracy/value");
    expect(primaryKey([], {})).toBeNull();
  });
  test("metricLabel and fmtDuration", () => {
    expect(metricLabel("accuracy/value")).toBe("accuracy");
    expect(metricLabel("latency/p95")).toBe("latency p95");
    expect(fmtDuration(42.4)).toBe("42s");
    expect(fmtDuration(250)).toBe("4m 10s");
    expect(fmtDuration(3900)).toBe("1h 5m");
  });
  test("bestBand prefers the test interval, then the seed t-interval", () => {
    expect(bestBand(SVM)).toEqual({ lo: 0.874, hi: 0.953, how: "Wilson, n = 180" });
    const seedOnly = { ...SVM, test_interval: null, primary: { mean: 0.9, std: 0.01, n: 3, ci_low: 0.875, ci_high: 0.925 } };
    expect(bestBand(seedOnly)).toEqual({ lo: 0.875, hi: 0.925, how: "t-interval over 3 seeds" });
    expect(bestBand({ ...SVM, test_interval: null })).toBeNull();
    expect(bestBand(null)).toBeNull();
  });
  test("verdictOf: best, inside the band, behind, unscored", () => {
    const band = bestBand(SVM);
    expect(verdictOf(SVM, SVM, band).kind).toBe("best");
    const rf = verdictOf(RF, SVM, band);
    expect(rf.kind).toBe("band");
    expect(rf.text).toBe(`${MINUS}0.037`);
    expect(rf.p).toBe("p 0.15");
    expect(rf.tip).toBe(
      "Mean inside the best's 95% CI: not proven worse. Exact sign test on 12 changed examples (9 fixed / 3 broken), p = 0.15. ≈250 examples for p < 0.05.",
    );
    const knn = verdictOf(KNN, SVM, band);
    expect(knn.kind).toBe("behind");
    expect(knn.text).toBe(`${MINUS}0.056`);
    expect(knn.p).toBe("");
    expect(verdictOf({ ...KNN, primary: null }, SVM, band).kind).toBe("none");
    const welch = verdictOf(
      { ...RF, vs_best: { delta: -0.02, p: 0.0004, fixed: null, broken: null, test: "welch", examples_needed: null } },
      SVM,
      null,
    );
    expect(welch.kind).toBe("behind");
    expect(welch.p).toBe("p < 0.001");
    expect(welch.tip).toBe("No 95% CI for the best group. Welch t-test over seeds, p < 0.001.");
  });
});

describe("Leaderboard panel", () => {
  test("one row per seed group with label, mean, spread, CI, second metric and verdict", () => {
    const { container } = render(<Leaderboard result={board()} />);
    const rows = [...container.querySelectorAll<HTMLElement>(".frow[data-row]")];
    expect(rows.map((r) => r.querySelector(".nm")?.textContent)).toEqual([
      "RBF-kernel SVM",
      "Baseline rf",
      "Baseline knn",
      "Baseline logreg",
    ]);
    expect(rows.map((r) => r.querySelector(".big")?.textContent)).toEqual(["0.9222", "0.8852", "0.8667", "0.8278"]);
    expect(rows.map((r) => r.querySelector(".f1")?.textContent)).toEqual(["0.9225", "0.8855", "0.8664", "0.8291"]);
    expect(rows.map((r) => r.querySelector(".vd")?.textContent)).toEqual([
      "best",
      `${MINUS}0.037p 0.15`,
      `${MINUS}0.056`,
      `${MINUS}0.094`,
    ]);
    expect(rows.map((r) => r.querySelector(".vg")?.getAttribute("class"))).toEqual([
      "vg best",
      "vg band",
      "vg behind",
      "vg behind",
    ]);
    const svm = within(rows[0] as HTMLElement);
    expect(svm.getByTitle("3 seeds, one score: the model ignores the seed").textContent).toBe("×3");
    expect(svm.getByTitle("test-set 95% CI (Wilson, n = 180)").textContent).toBe("0.874–0.953");
    expect(svm.getByTitle("RBF-kernel SVM beats the tree baselines")).toBeTruthy();
    expect(svm.getByText("agent:acceptance").className).toBe("who agent");
    expect(svm.getByText("6f71aa00@8f4cac4").getAttribute("href")).toBe("/r/20260926-6f71");
    expect(within(rows[1] as HTMLElement).getByTitle("std over 3 seeds").textContent).toBe("± 0.0064");
    const head = container.querySelector(".frow.head");
    expect([...(head?.children ?? [])].map((c) => c.textContent)).toEqual([
      "Idea",
      "accuracy",
      "seeds, 95% CI",
      "macro_f1",
      "vs best",
    ]);
  });

  test("plots seeds, diamonds, whiskers and the best band on one shared scale", () => {
    const { container } = render(<Leaderboard result={board()} />);
    const plots = [...container.querySelectorAll(".frow[data-row] .fplot svg")];
    expect(plots.length).toBe(4);
    // SVM: diamond (best) with ×3; rf: three seed dots, two of them stacked.
    expect(plots[0]?.querySelector("path.dia")?.getAttribute("class")).toBe("dia best");
    expect(plots[0]?.querySelector(".identical text")?.textContent).toBe("×3");
    expect([...(plots[1]?.querySelectorAll("circle.seed") ?? [])].map((c) => c.getAttribute("cy"))).toEqual([
      "30",
      "30",
      "22",
    ]);
    for (const p of plots) {
      expect(p.querySelectorAll("path.whisk").length).toBe(1);
      expect(p.querySelectorAll("rect.band").length).toBe(1);
    }
    // Domain: values span 0.766..0.953 -> nice [0.76, 0.96]; range [8, 592] at the 600 px fallback.
    // X(0.874) = 8 + (0.114 / 0.2) * 584 = 340.88; X(0.922222) = 8 + (0.162222 / 0.2) * 584 = 481.689.
    const band = plots[2]?.querySelector("rect.band");
    expect(Number(band?.getAttribute("x"))).toBeCloseTo(340.88, 2);
    expect(Number(plots[2]?.querySelector("line.bestline")?.getAttribute("x1"))).toBeCloseTo(481.689, 2);
    const ticks = [...container.querySelectorAll(".axisrow text.tk")].map((t) => t.textContent);
    expect(ticks.length).toBe(11);
    expect(ticks[0]).toBe("0.76");
    expect(ticks.at(-1)).toBe("0.96");
    expect(container.querySelector(".axisrow text.lbl-s")?.textContent).toBe("accuracy");
    expect([...container.querySelectorAll(".key span")].map((s) => s.textContent)).toEqual([
      "seed",
      "identical seeds",
      "test-set 95% CI",
      "best's CI",
    ]);
  });

  test("hovering an interval shows its exact numbers", () => {
    const { container } = render(<Leaderboard result={board()} />);
    const rfPlot = container.querySelectorAll(".frow[data-row] .fplot svg")[1] as SVGElement;
    const hit = rfPlot.querySelector("path.whisk")?.parentElement as Element;
    fireEvent.mouseEnter(hit, { clientX: 5, clientY: 5 });
    expect(screen.getByRole("tooltip").textContent).toBe(
      "Baseline rf\nmean 0.8852\ntest-set 95% CI 0.8300–0.9240\n(Wilson, n = 180)",
    );
  });

  test("noise: [test_set] hides seed marks; [seed] hides whiskers and CI text", () => {
    const { container, unmount } = render(<Leaderboard result={board({ noise: ["test_set"] })} />);
    expect(container.querySelectorAll(".fplot circle.seed, .fplot path.dia").length).toBe(0);
    expect(container.querySelectorAll(".fplot path.whisk").length).toBe(4);
    expect(container.querySelector(".frow.head")?.children[2]?.textContent).toBe("95% CI");
    unmount();
    const seedsOnly = render(<Leaderboard result={board({ noise: ["seed"] })} />).container;
    expect(seedsOnly.querySelectorAll(".fplot path.whisk").length).toBe(0);
    expect(seedsOnly.querySelectorAll(".fplot circle.seed").length).toBe(3);
    expect(seedsOnly.querySelector(".frow.head")?.children[2]?.textContent).toBe("seeds");
    expect(screen.queryByText("0.874–0.953")).toBeNull();
  });

  test("each scored non-best verdict links to the Examples page against the best run", () => {
    const rf = { ...RF, latest_run_id: "20260926-ef4f" };
    const knn = { ...KNN, latest_run_id: "20260926-3f7e" };
    const unscored = row({ group_id: "b2@c2", label: "unscored", vs_best: null });
    const hrefs = (meta: Record<string, unknown>) => {
      const { container, unmount } = render(<Leaderboard result={board(meta, [SVM, rf, knn, unscored])} />);
      const out = [...container.querySelectorAll(".frow[data-row]")].map(
        (r) => r.querySelector(".vd a")?.getAttribute("href") ?? null,
      );
      unmount();
      return out;
    };
    expect(hrefs({})).toEqual([
      null,
      "/x/20260926-ef4f/20260926-6f71?metric=accuracy",
      "/x/20260926-3f7e/20260926-6f71?metric=accuracy",
      null,
    ]);
    expect(hrefs({ primary: "macro_f1/value" })[1]).toBe("/x/20260926-ef4f/20260926-6f71?metric=macro_f1");
    expect(examplesHref("a b", "c", "solved@v2")).toBe("/x/a%20b/c?metric=solved%40v2");
  });

  test("single seed, missing primary, usage, and the empty state", () => {
    const one = row({
      group_id: "b1@c1",
      label: "one seed",
      run_ids: ["r9"],
      n: 1,
      single_seed: true,
      scores: { "accuracy/value": stat(0.95, 0, 1) },
      primary: stat(0.95, 0, 1),
      seed_values: { "accuracy/value": [0.95] },
      created_by: ["agent:tuner"],
      usage: { tokens_in: 1000, tokens_out: 200, usd: 1.234, seconds: 250, calls: 7 },
    });
    const none = row({ group_id: "b2@c2", label: "unscored", vs_best: null });
    const { container } = render(<Leaderboard result={board({}, [one, none])} />);
    const rows = [...container.querySelectorAll<HTMLElement>(".frow[data-row]")];
    expect(within(rows[0] as HTMLElement).getByTitle("One run: no seed noise estimate").textContent).toBe("single seed");
    expect(within(rows[0] as HTMLElement).getByTitle("7 calls, 1000 tokens in, 200 out").textContent).toBe("$1.23 · 4m 10s");
    expect(rows[1]?.querySelector(".big")?.textContent).toBe("—");
    expect(rows[1]?.querySelector(".vd")?.textContent).toBe("—");
    expect(rows[1]?.querySelectorAll(".fplot rect.mean").length).toBe(0);
    cleanup();
    render(<Leaderboard result={board({}, [])} />);
    expect(screen.getByText("No scored runs yet")).toBeTruthy();
  });
});
