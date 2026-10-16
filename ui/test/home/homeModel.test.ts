import { expect, test } from "bun:test";
import { groupFailures, isEmptyHome, reasonText, recentRows, runLabel, statusStrip, taskRows, utcDayStart } from "../../src/home/homeModel";
import type { FailureRow } from "../../src/api/models";
import { RUN_FAILED, RUN_RF, RUN_SVM, makeOverview } from "../pages/fixtures";
import { makeHosts } from "../pages/hostFixtures";
import { makeHomeSummary, runningRecord } from "./homeFixtures";

const NOW = Date.parse("2026-09-26T23:00:00Z");

test("statusStrip: live projects, running, queued, failed today, lost, GPUs busy, spent today", () => {
  expect(statusStrip(makeHomeSummary(), makeHosts(), NOW).map((k) => [k.label, k.value])).toEqual([
    ["projects with live runs", "1"],
    ["running", "1"],
    ["queued", "0"],
    ["failed today", "1"],
    ["lost", "0"],
    ["GPUs busy", "4 / 5"],
    ["spent today", "$332"],
  ]);
  expect(statusStrip(makeHomeSummary({ cost_today_usd: 41.2 }), [], NOW).at(-2)?.value).toBe("—");
  expect(statusStrip(makeHomeSummary({ cost_today_usd: 41.2 }), [], NOW).at(-1)?.value).toBe("$41");
  // the failure was yesterday seen from the next day
  expect(statusStrip(makeHomeSummary(), [], NOW + 86_400_000).find((k) => k.label === "failed today")?.value).toBe("0");
  expect(utcDayStart(NOW)).toBe(Date.parse("2026-09-26T00:00:00Z"));
});

test("isEmptyHome only for a store with no runs at all", () => {
  const empty = { ...makeOverview(), timeline: [], recent: [], running: [], failures: [], projects: [{ ...makeOverview().projects[0]!, runs: 0 }] };
  expect(isEmptyHome(empty)).toBe(true);
  expect(isEmptyHome(makeHomeSummary())).toBe(false);
  expect(isEmptyHome({ ...empty, recent: undefined, timeline: makeOverview().timeline })).toBe(false);
});

test("runLabel: the hub's view name, else the record's own title", () => {
  expect(runLabel(makeHomeSummary(), runningRecord())).toBe("model svm · seed 9");
  expect(runLabel(makeHomeSummary({ names: {} }), runningRecord({ hypothesis: "wider net", seed: 2 }))).toBe("wider net · seed 2");
  expect(runLabel(makeHomeSummary({ names: undefined }), runningRecord({ name: "my run" }))).toBe("my run");
});

test("taskRows: primary with direction, 7-day Δ, history, running now", () => {
  const [row] = taskRows(makeHomeSummary());
  expect(row).toMatchObject({ task: "toy-test", kind: "generic", metric: "accuracy", arrow: "↑", best: 0.9222222222222222, runs: 12, running: 1, improved: true, history: [0.85, 0.8852, 0.9222] });
  expect(row?.delta).toBeCloseTo(0.0370222, 5);
  const lower = taskRows(makeHomeSummary({ projects: [{ ...makeHomeSummary().projects[0]!, higher_is_better: false, best: 41.2, best_7d_ago: 44.3 }] }))[0];
  expect([lower?.arrow, lower?.improved]).toEqual(["↓", true]);
  const old = taskRows({ ...makeOverview(), running: makeHomeSummary().running })[0];
  expect([old?.metric, old?.delta, old?.running]).toEqual(["—", null, 1]);
});

test("recentRows: newest first, failures carry their stderr; an old backend falls back to the timeline", () => {
  const rows = recentRows(makeHomeSummary());
  expect(rows.map((r) => [r.name, r.reason])).toEqual([
    ["model svm · seed 3", "finished"],
    ["model svm · seed 4", "failed · exit 2"],
    ["model rf · seed 3", "finished"],
  ]);
  expect(rows[1]?.stderr).toContain(`${RUN_FAILED}/logs/stderr.log`);
  expect(rows[1]?.retried).toBe(true);
  // no `recent`: the unarchived timeline items, plus the (archived) failure from `failures`
  const old = recentRows(makeOverview());
  expect(old.map((r) => [r.runId, r.name, r.reason])).toEqual([
    [RUN_SVM, "RBF-kernel SVM", "finished"],
    [RUN_FAILED, "SVM", "failed · exit 2"],
    [RUN_RF, "Baseline rf", "finished"],
  ]);
});

test("reasonText: exit code for failures, the reason for lost runs", () => {
  expect(reasonText("failed", 137, null)).toBe("failed · exit 137");
  expect(reasonText("failed", null, null)).toBe("failed");
  expect(reasonText("lost", null, "host gone")).toBe("lost · host gone");
  expect(reasonText("finished", 0, null)).toBe("finished");
});

test("groupFailures joins rows with the same label and exit code, in first-seen order", () => {
  const f = (run_id: string, label: string, exit_code: number | null): FailureRow => ({ run_id, label, exit_code, created_at: "2026-09-26T21:00:00Z", stderr_path: `/s/${run_id}`, retried_ok: false });
  expect(groupFailures([f("a", "x", 1), f("b", "y", 1), f("c", "x", 1), f("d", "x", 2)]).map((g) => g.map((r) => r.run_id))).toEqual([["a", "c"], ["b"], ["d"]]);
});
