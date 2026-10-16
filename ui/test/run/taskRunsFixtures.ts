/**
 * `GET /tasks/toy-classifier/toy-test/runs` for the run page tests, consistent with
 * ../pages/fixtures.ts: the SVM config (RUN_SVM is seed 3, the best seed of the best
 * config) and the RF config, three seeds each.
 */
import type { Stats, TaskGroup, TaskRun, TaskRuns } from "../../src/api/models";
import { RUN_RF, RUN_SVM } from "../pages/fixtures";

export const SVM_GROUP = "63c2ec5f@8f4cac4";
export const RF_GROUP = "5a810ddb@2bbf5a3";
export const SVM_SIBLINGS = ["20260926-210302-toy-test-e294", "20260926-210304-toy-test-03bb"] as const;
export const RF_SIBLINGS = ["20260926-210028-toy-test-b5c4", "20260926-210030-toy-test-2e66"] as const;
const TASK_RUNS = "GET /api/v1/tasks/toy-classifier/toy-test/runs";

export function taskRun(over: Partial<TaskRun> & { run_id: string }): TaskRun {
  return {
    name: "model svm",
    derived_name: "model svm",
    renamed: false,
    group_id: SVM_GROUP,
    seed: 1,
    status: "finished",
    end_reason: null,
    exit_code: 0,
    created_by: "agent:acceptance",
    created_at: "2026-09-26T21:03:02Z",
    started_at: "2026-09-26T21:03:02Z",
    ended_at: "2026-09-26T21:03:03Z",
    host: "mbp.local",
    commit: null,
    params: { model: "svm" },
    tags: [],
    archived: false,
    starred: false,
    sweep_id: null,
    scores: {},
    primary: null,
    progress: null,
    gpu_hours: null,
    cost_usd: null,
    ...over,
  };
}

function scored(run_id: string, seed: number, acc: number, f1: number, created_at: string, rf = false): TaskRun {
  return taskRun({
    run_id,
    seed,
    created_at,
    scores: { "accuracy/value": acc, "macro_f1/value": f1 },
    primary: acc,
    ...(rf ? { name: "model rf", derived_name: "model rf", group_id: RF_GROUP, params: { model: "rf" }, created_by: "human" } : {}),
  });
}

const mean = (v: number[]): number => v.reduce((a, b) => a + b, 0) / v.length;
const sd = (v: number[]): number => Math.sqrt(v.reduce((a, x) => a + (x - mean(v)) ** 2, 0) / (v.length - 1));

function group(id: string, name: string, members: TaskRun[], lo: number, hi: number, best: boolean): TaskGroup {
  const acc = members.map((r) => r.primary ?? 0);
  const f1 = members.map((r) => r.scores["macro_f1/value"] ?? 0);
  const primary: Stats = { mean: mean(acc), std: sd(acc), n: acc.length, ci_low: null, ci_high: null };
  return {
    group_id: id,
    name,
    run_ids: members.map((r) => r.run_id),
    n: members.length,
    primary,
    test_interval: { lo, hi, method: "wilson", n: 180 },
    scores: { "accuracy/value": mean(acc), "macro_f1/value": mean(f1) },
    seed_values: acc,
    within_noise_of_best: !best,
    vs_best: null,
    is_best: best,
  };
}

export function makeTaskRuns(over: Partial<TaskRuns> = {}): TaskRuns {
  const runs = [
    scored(SVM_SIBLINGS[0], 1, 0.88, 0.92, "2026-09-26T21:03:02Z"),
    scored(SVM_SIBLINGS[1], 2, 0.89, 0.923, "2026-09-26T21:03:04Z"),
    scored(RUN_SVM, 3, 0.9222222222222223, 0.9224758529636579, "2026-09-26T21:03:06Z"),
    scored(RF_SIBLINGS[0], 1, 0.8833333333333333, 0.88, "2026-09-26T21:00:28Z", true),
    scored(RF_SIBLINGS[1], 2, 0.8777777777777778, 0.87, "2026-09-26T21:00:30Z", true),
    scored(RUN_RF, 3, 0.8944444444444445, 0.89, "2026-09-26T21:00:32Z", true),
  ];
  return {
    project: "toy-classifier",
    task: "toy-test",
    kind: "generic",
    primary: "accuracy/value",
    higher_is_better: true,
    unit: "",
    value_format: "fraction",
    varying_keys: ["model"],
    metric_names: ["train_accuracy"],
    score_keys: ["accuracy/value", "macro_f1/value"],
    key_parts: null,
    metric_versions: { accuracy: "v1", macro_f1: "v1" },
    runs,
    groups: [
      group(SVM_GROUP, "model svm", runs.slice(0, 3), 0.874, 0.953, true),
      group(RF_GROUP, "model rf", runs.slice(3), 0.83, 0.924, false),
    ],
    ...over,
  };
}

/** mockApi routes for the task runs, whether or not the client sends `archived=false`. */
export function taskRunsRoutes(body: TaskRuns = makeTaskRuns(), archived = false): Record<string, unknown> {
  return archived
    ? { [`${TASK_RUNS}?archived=true`]: body }
    : { [TASK_RUNS]: body, [`${TASK_RUNS}?archived=false`]: body };
}
