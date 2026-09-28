import type {
  ExampleDiff,
  Leaderboard,
  OverviewSummary,
  RunDetail,
  RunRecord,
} from "../../src/pages/components/types";

export const RUN_SVM = "20260926-210306-toy-test-6f71";
export const RUN_RF = "20260926-210032-toy-test-ef4f";
export const RUN_FAILED = "20260926-210158-toy-test-58c5";
export const STORE = "/private/tmp/hx-accept/home/store/toy-classifier/runs";
export const REPO = "/private/tmp/hx-accept/toy";
export const SVM_HYPOTHESIS =
  "RBF-kernel SVM should beat RF/KNN/logreg because the class clusters are round";

export function makeRecord(over: Partial<RunRecord> = {}): RunRecord {
  const runId = over.run_id ?? RUN_SVM;
  return {
    run_id: runId,
    project: "toy-classifier",
    task: "toy-test",
    hypothesis: SVM_HYPOTHESIS,
    kind: "full",
    parent: null,
    stage: null,
    command: ["python", "train_eval.py", "--model", "svm", "--seed=3"],
    command_template: ["python", "train_eval.py", "--model", "svm", "--seed={seed}"],
    params: {},
    vars: {},
    cwd: REPO,
    environment_id: "env-5c1e",
    host: "mbp.local",
    executor: { type: "local", pid: null, pid_create_time: null, child_pid: null },
    git: {
      repo: null,
      commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
      branch: "main",
      dirty: false,
      untracked_count: 2,
      untracked: ["scratch.py", "notes.txt"],
    },
    datasets: [
      {
        name: "toyset",
        version: "v1",
        split: "test",
        host: "local",
        path: `${REPO}/data/test.jsonl`,
        hash: "xxh3:a6ff57960a911828",
        hash_mode: null,
        size: 26123,
        checked_at: null,
      },
    ],
    seed: 3,
    config_hash: "sha256:63c2ec5fb24db57e",
    status: "finished",
    created_at: "2026-09-26T21:03:06.685638Z",
    started_at: "2026-09-26T21:03:06.756813Z",
    ended_at: "2026-09-26T21:03:07.578937Z",
    exit_code: 0,
    artifacts: [
      {
        kind: "checkpoint",
        path: `${STORE}/${runId}/model.pkl`,
        host: "local",
        size: 18494,
        step: null,
        metrics: {},
      },
    ],
    tags: ["best", "svm"],
    starred: false,
    archived: false,
    created_by: "agent:acceptance",
    usage: null,
    ...over,
  };
}

export function makeDetail(over: Partial<RunRecord> = {}, rest: Partial<RunDetail> = {}): RunDetail {
  const record = makeRecord(over);
  const dir = `${STORE}/${record.run_id}`;
  return {
    record,
    scores: [
      {
        metric: "accuracy",
        version: "v1",
        key: "value",
        value: 0.9222222222222223,
        error: null,
        source_hash: "sha256:e662a37bb8a556fd",
        created_at: "2026-09-26T21:03:08.286629Z",
      },
      {
        metric: "macro_f1",
        version: "v1",
        key: "value",
        value: 0.9224758529636579,
        error: null,
        source_hash: "sha256:28127f3db7be711f",
        created_at: "2026-09-26T21:03:08.286629Z",
      },
    ],
    paths: {
      run_dir: dir,
      cwd: REPO,
      stdout: `${dir}/logs/stdout.log`,
      stderr: `${dir}/logs/stderr.log`,
      predictions: `${dir}/predictions`,
      env: `${dir}/env`,
      repo: REPO,
    },
    notes: "\n## 2026-09-26T21:03:56.036288+00:00 — agent:acceptance\n\nRBF SVM beats prior best (rf).\n",
    has_diff: false,
    metric_names: ["train_accuracy"],
    children: [],
    ...rest,
  };
}

export function makeBoard(): Leaderboard {
  return {
    project: "toy-classifier",
    task: "toy-test",
    primary: "accuracy/value",
    higher_is_better: true,
    metric_versions: { accuracy: "v1", macro_f1: "v1" },
    rows: [
      {
        group_id: "63c2ec5f@8f4cac4",
        run_ids: ["20260926-210302-toy-test-e294", "20260926-210304-toy-test-03bb", RUN_SVM],
        latest_run_id: RUN_SVM,
        hypothesis: SVM_HYPOTHESIS,
        label: "RBF-kernel SVM",
        commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
        config_hash: "sha256:63c2ec5fb24db57e",
        n: 3,
        scores: {},
        primary: {
          mean: 0.9222222222222222,
          std: 0,
          n: 3,
          ci_low: 0.9222222222222222,
          ci_high: 0.9222222222222222,
        },
        single_seed: false,
        within_noise_of_best: null,
        seed_values: { "accuracy/value": [0.9222222222222222, 0.9222222222222222, 0.9222222222222222] },
        identical_seeds: true,
        test_interval: { lo: 0.874, hi: 0.953, method: "wilson", n: 180 },
        vs_best: null,
        created_by: ["agent:acceptance"],
        usage: null,
      },
      {
        group_id: "5a810ddb@2bbf5a3",
        run_ids: ["20260926-210028-toy-test-b5c4", "20260926-210030-toy-test-2e66", RUN_RF],
        latest_run_id: RUN_RF,
        hypothesis: "baseline rf",
        label: "Baseline rf",
        commit: "2bbf5a3c81bfc657dea6d28bf0b3f057409602ad",
        config_hash: "sha256:5a810ddb4e0c2f19",
        n: 3,
        scores: {},
        primary: {
          mean: 0.8851851851851852,
          std: 0.006415002990995819,
          n: 3,
          ci_low: 0.8692481481481482,
          ci_high: 0.9011222222222222,
        },
        single_seed: false,
        within_noise_of_best: true,
        seed_values: { "accuracy/value": [0.8833333333333333, 0.8777777777777778, 0.8944444444444445] },
        identical_seeds: false,
        test_interval: { lo: 0.83, hi: 0.924, method: "wilson", n: 180 },
        // backend `_versus`: fixed = best passes and this row fails (the Task 12 fixture agrees)
        vs_best: { delta: -0.037, p: 0.146, fixed: 9, broken: 3, test: "sign", examples_needed: 250 },
        created_by: ["human"],
        usage: null,
      },
    ],
    needs_reeval: [],
    unscored: [],
    headline: "SVM +0.037 over rf, p = 0.15",
    kind: "generic",
    stat_strip: [],
  };
}

export function makeOverview(): OverviewSummary {
  const band = { lo: 0.874, hi: 0.953, method: "wilson" as const, n: 180 };
  return {
    headline: "Idle. SVM leads toy-test by 0.037, p = 0.15",
    counts: { "runs today": 19, failed: 3, task: 1 },
    timeline: [
      {
        run_id: RUN_SVM,
        project: "toy-classifier",
        task: "toy-test",
        created_at: "2026-09-26T21:03:06Z",
        created_by: "agent:acceptance",
        status: "finished",
        archived: false,
        group_id: "63c2ec5f@8f4cac4",
        is_best: true,
        label: "RBF-kernel SVM",
      },
      {
        run_id: RUN_FAILED,
        project: "toy-classifier",
        task: "toy-test",
        created_at: "2026-09-26T21:01:58Z",
        created_by: "agent:acceptance",
        status: "failed",
        archived: true,
        group_id: null,
        is_best: false,
        label: "RBF-kernel SVM",
      },
      {
        run_id: RUN_RF,
        project: "toy-classifier",
        task: "toy-test",
        created_at: "2026-09-26T21:00:32Z",
        created_by: "human",
        status: "finished",
        archived: false,
        group_id: "5a810ddb@2bbf5a3",
        is_best: false,
        label: "Baseline rf",
      },
    ],
    ideas: [
      {
        project: "toy-classifier",
        task: "toy-test",
        group_id: "63c2ec5f@8f4cac4",
        label: "RBF-kernel SVM",
        created_by: "agent:acceptance",
        created_at: "2026-09-26T21:03:06Z",
        statuses: ["finished", "finished", "finished"],
        primary: { mean: 0.9222222222222222, std: 0, n: 3, ci_low: null, ci_high: null },
        test_interval: band,
        identical_seeds: true,
        best_band: band,
        unit: "",
      },
      {
        project: "toy-classifier",
        task: "toy-test",
        group_id: "63c2ec5f@0000000",
        label: "RBF-kernel SVM",
        created_by: "agent:acceptance",
        created_at: "2026-09-26T21:01:58Z",
        statuses: ["failed", "failed", "failed"],
        primary: null,
        test_interval: null,
        identical_seeds: false,
        best_band: band,
        unit: "",
      },
      {
        project: "toy-classifier",
        task: "toy-test",
        group_id: "5a810ddb@2bbf5a3",
        label: "Baseline rf",
        created_by: "human",
        created_at: "2026-09-26T21:00:32Z",
        statuses: ["finished", "finished", "finished"],
        primary: { mean: 0.8851851851851852, std: 0.006415002990995819, n: 3, ci_low: null, ci_high: null },
        test_interval: { lo: 0.83, hi: 0.924, method: "wilson", n: 180 },
        identical_seeds: false,
        best_band: band,
        unit: "",
      },
    ],
    running: [],
    failures: [
      {
        run_id: RUN_FAILED,
        label: "SVM",
        exit_code: 2,
        created_at: "2026-09-26T21:01:58Z",
        stderr_path: `${STORE}/${RUN_FAILED}/logs/stderr.log`,
        retried_ok: true,
      },
    ],
    projects: [
      { project: "toy-classifier", task: "toy-test", runs: 12, best: 0.9222222222222222, kind: "generic", unit: "" },
    ],
  };
}

export function makeDiff(): ExampleDiff {
  return {
    a: RUN_RF,
    b: RUN_SVM,
    metric: "accuracy@v1",
    field: "correct",
    fixed: ["test-0", "test-110", "test-116", "test-12", "test-156", "test-177", "test-21", "test-63", "test-83"],
    broken: ["test-137", "test-167", "test-30"],
    both_pass: 157,
    both_fail: 11,
  };
}
