/** An overview as a v5 hub sends it (with recent, names, progress and the task trend fields). */
import type { OverviewSummary, RunRecord } from "../../src/api/models";
import { RUN_FAILED, RUN_RF, RUN_SVM, makeOverview, makeRecord } from "../pages/fixtures";

export const RUNNING = "20260926-221000-toy-test-aa11";

/** The one running run of `makeHomeSummary`. */
export function runningRecord(over: Partial<RunRecord> = {}): RunRecord {
  return makeRecord({
    run_id: RUNNING,
    status: "running",
    started_at: "2026-09-26T22:10:00Z",
    ended_at: null,
    exit_code: null,
    created_by: "agent:tuner",
    ...over,
  });
}

export function makeHomeSummary(over: Partial<OverviewSummary> = {}): OverviewSummary {
  const base = makeOverview();
  return {
    ...base,
    counts: { ...base.counts, running: 1, queued: 0, lost: 0 },
    // a v5 hub's `recent` holds unarchived runs only, so the failure in it is unarchived too
    timeline: base.timeline.map((t) => (t.run_id === RUN_FAILED ? { ...t, archived: false } : t)),
    running: [runningRecord()],
    projects: [{ ...base.projects[0]!, primary: "accuracy/value", higher_is_better: true, best_7d_ago: 0.8852, best_history: [0.85, 0.8852, 0.9222], running: 1, queued: 0 }],
    recent: [
      { run_id: RUN_SVM, project: "toy-classifier", task: "toy-test", name: "model svm · seed 3", status: "finished", end_reason: null, exit_code: 0, created_at: "2026-09-26T21:03:06Z", created_by: "agent:acceptance", hypothesis: "RBF-kernel SVM should beat RF", primary: 0.9222, delta_best: 0 },
      { run_id: RUN_FAILED, project: "toy-classifier", task: "toy-test", name: "model svm · seed 4", status: "failed", end_reason: null, exit_code: 2, created_at: "2026-09-26T21:01:58Z", created_by: "agent:acceptance", hypothesis: "RBF-kernel SVM should beat RF", primary: null, delta_best: null },
      { run_id: RUN_RF, project: "toy-classifier", task: "toy-test", name: "model rf · seed 3", status: "finished", end_reason: null, exit_code: 0, created_at: "2026-09-26T21:00:32Z", created_by: "human", hypothesis: "baseline rf", primary: 0.8944, delta_best: -0.0278 },
    ],
    names: { [RUNNING]: "model svm · seed 9" },
    // a v5 hub sends no progress or ETA (runs report no total): the latest step and value only
    progress: { [RUNNING]: { progress: null, metric: "val/accuracy", step: 1200, value: 0.901, eta_seconds: null } },
    ...over,
  };
}
