/**
 * `GET /api/v1/tasks/{p}/{t}/runs` fixtures (synthetic names only).
 *
 * Every `TaskRun` carries `commit` and every `TaskRuns` `metric_versions`, as the server sends them.
 *
 * `makeTaskRuns()`: training task `toy-proj/toy-task`, primary `top1/value` (higher is
 * better), four configs:
 *   g-a "lr 3e-4 · beam 10"  a1 0.912, a2 0.910 (tag final), a3 running   best
 *   g-b "lr 1e-4 · beam 10"  b1 0.899, b2 0.897 (host dgx)                outside noise, p 0.01
 *   g-c "lr 1e-3 · beam 1"   c1 failed (exit 1), c2 queued                 unscored
 *   g-d "baseline"           d1 0.905, seed null, human:sam, superseded    inside noise, p 0.24
 * `makeEvalTaskRuns()`: eval task, keys `reported/<test-a..test-e>.<model-x|model-y>.<top1|top10>`,
 * one run per `db v1..v3` (v3 best), `key_parts` `["dataset", "model", "metric"]`; run v1
 * lacks `reported/test-e.model-y.top1`.
 * `makeBenchTaskRuns()`: a `system_bench`-like task whose score keys differ in direction.
 */
import type { Stats, TaskGroup, TaskRun, TaskRuns, ViewDocument, ViewInfo } from "../../src/api/models";
import { RUN_RF, RUN_SVM } from "../pages/fixtures";

export const PROJECT = "toy-proj";
export const TASK = "toy-task";
export const BASE = `/api/v1/tasks/${PROJECT}/${TASK}`;

export function makeTaskRun(over: Partial<TaskRun> = {}): TaskRun {
  return {
    run_id: "run-a1",
    name: "lr 3e-4 · beam 10",
    derived_name: "lr 3e-4 · beam 10",
    renamed: false,
    group_id: "g-a",
    seed: 1,
    status: "finished",
    end_reason: null,
    exit_code: 0,
    created_by: "agent:tuner",
    created_at: "2026-10-03T09:00:00Z",
    started_at: "2026-10-03T09:00:05Z",
    ended_at: "2026-10-03T10:00:00Z",
    host: "gpu1",
    params: { lr: "3e-4", beam: "10" },
    tags: [],
    archived: false,
    starred: false,
    sweep_id: null,
    scores: { "top1/value": 0.912, "top1/final": 0.91 },
    primary: 0.912,
    progress: 1,
    gpu_hours: 1.5,
    cost_usd: null,
    commit: "8f4cac43877b",
    ...over,
  };
}

const stats = (mean: number, std: number, n: number): Stats => ({
  mean,
  std,
  n,
  ci_low: n > 1 ? mean - 0.002 : null,
  ci_high: n > 1 ? mean + 0.002 : null,
});

export function makeTaskGroup(over: Partial<TaskGroup> = {}): TaskGroup {
  return {
    group_id: "g-a",
    name: "lr 3e-4 · beam 10",
    run_ids: ["run-a1"],
    n: 1,
    primary: stats(0.912, 0, 1),
    test_interval: null,
    scores: { "top1/value": 0.912 },
    seed_values: [0.912],
    within_noise_of_best: true,
    vs_best: null,
    is_best: false,
    ...over,
  };
}

const B = { name: "lr 1e-4 · beam 10", derived_name: "lr 1e-4 · beam 10", params: { lr: "1e-4", beam: "10" } };
const C = { name: "lr 1e-3 · beam 1", derived_name: "lr 1e-3 · beam 1", params: { lr: "1e-3", beam: "1" } };

export function makeTaskRuns(over: Partial<TaskRuns> = {}): TaskRuns {
  const runs: TaskRun[] = [
    makeTaskRun({ run_id: "run-a1" }),
    makeTaskRun({ run_id: "run-a2", seed: 2, primary: 0.91, scores: { "top1/value": 0.91, "top1/final": 0.905 }, created_at: "2026-10-03T09:10:00Z", tags: ["final"] }),
    makeTaskRun({ run_id: "run-a3", seed: 3, status: "running", primary: null, scores: {}, progress: 0.4, ended_at: null, created_at: "2026-10-03T11:00:00Z", gpu_hours: null }),
    makeTaskRun({ run_id: "run-b1", group_id: "g-b", ...B, primary: 0.899, scores: { "top1/value": 0.899, "top1/final": 0.894 }, created_at: "2026-10-03T09:20:00Z", host: "dgx" }),
    makeTaskRun({ run_id: "run-b2", group_id: "g-b", seed: 2, ...B, primary: 0.897, scores: { "top1/value": 0.897, "top1/final": 0.892 }, created_at: "2026-10-03T09:30:00Z", host: "dgx" }),
    makeTaskRun({ run_id: "run-c1", group_id: "g-c", ...C, status: "failed", exit_code: 1, primary: null, scores: {}, created_at: "2026-10-03T09:40:00Z" }),
    makeTaskRun({ run_id: "run-c2", group_id: "g-c", seed: 2, ...C, status: "queued", primary: null, scores: {}, started_at: null, ended_at: null, created_at: "2026-10-03T11:10:00Z", gpu_hours: null }),
    makeTaskRun({ run_id: "run-d1", group_id: "g-d", seed: null, name: "baseline", derived_name: "baseline", params: {}, created_by: "human:sam", tags: ["superseded"], primary: 0.905, scores: { "top1/value": 0.905 }, created_at: "2026-10-02T08:00:00Z", commit: "b82f04c11aa0" }),
  ];
  const groups: TaskGroup[] = [
    makeTaskGroup({ group_id: "g-a", run_ids: ["run-a1", "run-a2", "run-a3"], n: 2, primary: stats(0.911, 0.0014, 2), test_interval: { lo: 0.905, hi: 0.917, method: "wilson", n: 2000 }, scores: { "top1/value": 0.911, "top1/final": 0.9075 }, seed_values: [0.912, 0.91], is_best: true }),
    makeTaskGroup({ group_id: "g-b", name: B.name, run_ids: ["run-b1", "run-b2"], n: 2, primary: stats(0.898, 0.0014, 2), test_interval: { lo: 0.892, hi: 0.904, method: "wilson", n: 2000 }, scores: { "top1/value": 0.898, "top1/final": 0.893 }, seed_values: [0.899, 0.897], within_noise_of_best: false, vs_best: { delta: -0.013, p: 0.01, fixed: 3, broken: 29, test: "sign", examples_needed: null } }),
    makeTaskGroup({ group_id: "g-c", name: C.name, run_ids: ["run-c1", "run-c2"], n: 0, primary: null, scores: {}, seed_values: [], within_noise_of_best: false }),
    makeTaskGroup({ group_id: "g-d", name: "baseline", run_ids: ["run-d1"], n: 1, primary: stats(0.905, 0, 1), test_interval: { lo: 0.899, hi: 0.911, method: "wilson", n: 2000 }, scores: { "top1/value": 0.905 }, seed_values: [0.905], vs_best: { delta: -0.006, p: 0.24, fixed: 10, broken: 22, test: "sign", examples_needed: null } }),
  ];
  return {
    project: PROJECT,
    task: TASK,
    kind: "training",
    primary: "top1/value",
    higher_is_better: true,
    unit: "",
    value_format: "fraction",
    varying_keys: ["lr", "beam"],
    metric_names: ["train/loss", "val/loss", "val/top1", "sys/gpu_util"],
    score_keys: ["top1/value", "top1/final"],
    metric_versions: { top1: "v1" },
    key_higher_is_better: { "top1/value": true, "top1/final": true },
    key_parts: null,
    runs,
    groups,
    ...over,
  };
}

export const DATASETS = ["test-a", "test-b", "test-c", "test-d", "test-e"] as const;
export const MODELS = ["model-x", "model-y"] as const;
export const METRICS = ["top1", "top10"] as const;
export const EVAL_PRIMARY = "reported/test-a.model-x.top10";

/** `0.4 + 0.1·db − 0.05·dataset − 0.03·model + 0.3·(metric is top10)`, three decimals. */
export function evalValue(db: number, d: number, m: number, t: number): number {
  return Number((0.4 + 0.1 * db - 0.05 * d - 0.03 * m + 0.3 * t).toFixed(3));
}

export function makeEvalTaskRuns(): TaskRuns {
  const keys = DATASETS.flatMap((d) => MODELS.flatMap((m) => METRICS.map((t) => `reported/${d}.${m}.${t}`)));
  const runs = ["v1", "v2", "v3"].map((db, i) => {
    const scores: Record<string, number> = {};
    DATASETS.forEach((d, di) => MODELS.forEach((m, mi) => METRICS.forEach((t, ti) => {
      scores[`reported/${d}.${m}.${t}`] = evalValue(i, di, mi, ti);
    })));
    if (db === "v1") delete scores["reported/test-e.model-y.top1"];
    return makeTaskRun({
      run_id: `run-${db}`,
      group_id: `g-${db}`,
      seed: null,
      name: `db ${db}`,
      derived_name: `db ${db}`,
      params: { db },
      created_at: `2026-10-0${i + 1}T09:00:00Z`,
      scores,
      primary: scores[EVAL_PRIMARY] ?? null,
      gpu_hours: null,
    });
  });
  const groups = runs.map((run) =>
    makeTaskGroup({
      group_id: run.group_id,
      name: run.derived_name,
      run_ids: [run.run_id],
      primary: stats(run.primary ?? 0, 0, 1),
      scores: run.scores,
      seed_values: [run.primary ?? 0],
      is_best: run.run_id === "run-v3",
      within_noise_of_best: run.run_id === "run-v3",
    }),
  );
  return {
    project: PROJECT,
    task: TASK,
    kind: "generic",
    primary: EVAL_PRIMARY,
    higher_is_better: true,
    unit: "",
    value_format: "fraction",
    varying_keys: ["db"],
    metric_names: [],
    score_keys: keys,
    metric_versions: { reported: "v1" },
    key_higher_is_better: Object.fromEntries(keys.map((k) => [k, true])),
    key_parts: ["dataset", "model", "metric"],
    runs,
    groups,
  };
}

/**
 * A `system_bench`-like task: primary `latency/p95` (lower is better), `throughput/rps`
 * (higher is better) and `throughput/peak` (direction unknown: the task's). Configs
 * `fast` (40 ms, 900 rps, peak 1000) and `wide` (60 ms, 1200 rps, peak 1100).
 */
export function makeBenchTaskRuns(): TaskRuns {
  const bench = [
    ["fast", 40, 900, 1000],
    ["wide", 60, 1200, 1100],
  ] as const;
  const runs = bench.map(([id, latency, rps, peak], i) =>
    makeTaskRun({
      run_id: `run-${id}`,
      group_id: `g-${id}`,
      seed: null,
      name: id,
      derived_name: id,
      params: { cache: id },
      created_at: `2026-10-0${i + 1}T09:00:00Z`,
      scores: { "latency/p95": latency, "throughput/rps": rps, "throughput/peak": peak },
      primary: latency,
      gpu_hours: null,
    }),
  );
  const groups = runs.map((run) =>
    makeTaskGroup({
      group_id: run.group_id,
      name: run.derived_name,
      run_ids: [run.run_id],
      primary: stats(run.primary ?? 0, 0, 1),
      scores: run.scores,
      seed_values: [run.primary ?? 0],
      is_best: run.run_id === "run-fast",
    }),
  );
  return {
    project: PROJECT,
    task: TASK,
    kind: "system_bench",
    primary: "latency/p95",
    higher_is_better: false,
    unit: "ms",
    value_format: "duration",
    varying_keys: ["cache"],
    metric_names: [],
    score_keys: ["latency/p95", "throughput/peak", "throughput/rps"],
    metric_versions: { latency: "v1", throughput: "v1" },
    key_higher_is_better: { "latency/p95": false, "throughput/rps": true },
    key_parts: null,
    runs,
    groups,
  };
}

/** `toy-classifier/toy-test` (the leaderboard of `test/pages/fixtures.ts` `makeBoard()`). */
export function toyTaskRuns(): TaskRuns {
  const svm = ["20260926-210302-toy-test-e294", "20260926-210304-toy-test-03bb", RUN_SVM];
  const runs = svm.map((run_id, i) =>
    makeTaskRun({
      run_id,
      group_id: "63c2ec5f@8f4cac4",
      seed: i + 1,
      name: "model svm",
      derived_name: "model svm",
      params: { model: "svm" },
      created_by: "agent:acceptance",
      created_at: `2026-09-26T21:03:0${2 + 2 * i}.000000Z`,
      scores: { "accuracy/value": 0.92 + i * 0.001 },
      primary: 0.92 + i * 0.001,
    }),
  );
  runs.push(
    makeTaskRun({
      run_id: RUN_RF,
      group_id: "5a810ddb@8f4cac4",
      seed: 9,
      name: "model rf",
      derived_name: "model rf",
      params: { model: "rf" },
      created_at: "2026-09-26T21:00:32.000000Z",
      scores: { "accuracy/value": 0.885 },
      primary: 0.885,
    }),
  );
  return {
    project: "toy-classifier",
    task: "toy-test",
    kind: "generic",
    primary: "accuracy/value",
    higher_is_better: true,
    unit: "",
    value_format: "fraction",
    varying_keys: ["model"],
    metric_names: [],
    score_keys: ["accuracy/value"],
    metric_versions: { accuracy: "v1" },
    key_higher_is_better: { "accuracy/value": true },
    key_parts: null,
    runs,
    groups: [
      makeTaskGroup({ group_id: "63c2ec5f@8f4cac4", name: "model svm", run_ids: svm, n: 3, primary: stats(0.921, 0.001, 3), test_interval: { lo: 0.88, hi: 0.95, method: "wilson", n: 90 }, scores: { "accuracy/value": 0.921 }, seed_values: [0.92, 0.921, 0.922], is_best: true }),
      makeTaskGroup({ group_id: "5a810ddb@8f4cac4", name: "model rf", run_ids: [RUN_RF], n: 1, primary: stats(0.885, 0, 1), scores: { "accuracy/value": 0.885 }, seed_values: [0.885] }),
    ],
  };
}

/** The resolved preset view (`GET .../views/overview`) for a kind. */
export function presetDoc(kind: "generic" | "training" | "system_bench" | "agent_iteration" = "generic"): ViewDocument {
  const info: ViewInfo = { name: "overview", title: "Overview", origin: "preset", path: null, kind };
  const panels: ViewDocument["view"]["panels"] =
    kind === "training"
      ? [
          { type: "stat_strip", title: "Summary", layout: { span: 12, row: 1 } },
          { type: "leaderboard", title: "Configs", noise: ["seed", "test_set"], layout: { span: 12, row: 2 } },
          { type: "curves", title: "Curves", data: { metrics: ["train/loss"], group_by: "group" }, layout: { span: 12, row: 3 } },
          { type: "table", title: "Runs", data: { source: "runs", fields: ["run_id"] }, layout: { span: 8, row: 4 } },
          { type: "curves", title: "Checkpoints", data: { metrics: ["val/top1"], group_by: "run" }, layout: { span: 12, row: 5 } },
        ]
      : [
          { type: "stat_strip", title: "Summary", layout: { span: 12, row: 1 } },
          { type: "leaderboard", title: "Leaderboard", noise: ["seed", "test_set"], layout: { span: 12, row: 2 } },
        ];
  return { info, text: "title: overview\n", view: { title: "overview", panels } };
}
