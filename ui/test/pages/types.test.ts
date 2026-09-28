import { expect, test } from "bun:test";
import { ACTIVE_STATUSES, FAILED_STATUSES, type RunStatus } from "../../src/pages/components/types";
import { makeBoard, makeDetail, makeOverview } from "./fixtures";

const ALL: RunStatus[] = ["queued", "running", "finished", "failed", "killed", "lost"];

test("every status is active, failed, or finished", () => {
  expect(ALL.filter((s) => ACTIVE_STATUSES.has(s))).toEqual(["queued", "running"]);
  expect(ALL.filter((s) => FAILED_STATUSES.has(s))).toEqual(["failed", "killed", "lost"]);
  expect(ALL.filter((s) => !ACTIVE_STATUSES.has(s) && !FAILED_STATUSES.has(s))).toEqual(["finished"]);
});

test("fixtures mirror the ui-v4 mockup numbers", () => {
  expect(makeDetail().record.run_id).toBe("20260926-210306-toy-test-6f71");
  expect(makeBoard().rows.map((r) => r.label)).toEqual(["RBF-kernel SVM", "Baseline rf"]);
  expect(makeOverview().headline).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
});

test("the rf row's vs_best counts match the backend's _versus meaning", () => {
  // fixed = the best passes where this row fails; the SVM fixes 9 of rf's examples, breaks 3
  const rf = makeBoard().rows[1];
  expect(rf?.vs_best).toEqual({ delta: -0.037, p: 0.146, fixed: 9, broken: 3, test: "sign", examples_needed: 250 });
});
