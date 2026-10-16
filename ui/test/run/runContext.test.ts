import { describe, expect, test } from "bun:test";
import { colorFor } from "../../src/lib/color";
import { asLogStream, asRunTab, compareTarget, exampleTargets, runIdentity, shownTab } from "../../src/run/runContext";
import { defaultSelection, visibleIdentities } from "../../src/task/useRunSelection";
import { RUN_RF, RUN_SVM } from "../pages/fixtures";
import { RF_GROUP, SVM_GROUP, SVM_SIBLINGS, makeTaskRuns } from "./taskRunsFixtures";

describe("tabs", () => {
  test("only known tabs and log streams pass (values come from the URL)", () => {
    expect(asRunTab("files")).toBe("files");
    expect(asRunTab("view:x")).toBeNull();
    expect(asLogStream("stderr")).toBe("stderr");
    expect(asLogStream("../etc/passwd")).toBeNull();
  });

  test("shownTab: ?tab= wins, an old ?log= link opens Logs, else Overview", () => {
    expect(shownTab("charts", "stderr")).toBe("charts");
    expect(shownTab(undefined, "stderr")).toBe("logs");
    expect(shownTab("nope", undefined)).toBe("overview");
  });
});

describe("runIdentity", () => {
  test("the run's group colour is its index in the Task page's default selection", () => {
    const data = makeTaskRuns();
    const id = runIdentity(data, RUN_SVM);
    expect(id.group?.group_id).toBe(SVM_GROUP);
    expect(id.siblings.map((r) => r.run_id)).toEqual([...SVM_SIBLINGS]);
    expect(id.color).toBe(colorFor(SVM_GROUP, visibleIdentities(defaultSelection(data.higher_is_better), data)));
    expect(id.color).not.toBe("var(--c0)");
  });

  test("the colour follows the task's best-first order: a lower-is-better task puts the smallest mean first", () => {
    expect([runIdentity(makeTaskRuns(), RUN_SVM).color, runIdentity(makeTaskRuns(), RUN_RF).color]).toEqual(["var(--c1)", "var(--c2)"]);
    const lower = makeTaskRuns({ higher_is_better: false });
    expect([runIdentity(lower, RUN_RF).color, runIdentity(lower, RUN_SVM).color]).toEqual(["var(--c1)", "var(--c2)"]);
  });

  test("a run missing from the task's runs is neutral grey", () => {
    expect(runIdentity(makeTaskRuns(), "other").color).toBe("var(--c0)");
    expect(runIdentity(null, RUN_SVM)).toEqual({ run: null, group: null, siblings: [], color: "var(--c0)" });
  });
});

describe("examples targets", () => {
  test("other scored configs, best first, each by its newest run", () => {
    const data = makeTaskRuns();
    expect(exampleTargets(data, RUN_SVM).map((t) => [t.groupId, t.runId, t.name])).toEqual([[RF_GROUP, RUN_RF, "model rf"]]);
    expect(compareTarget(data, RUN_SVM)).toBe(RUN_RF);
    expect(compareTarget(data, RUN_RF)).toBe(RUN_SVM);
  });

  test("lower-is-better tasks rank the smallest mean first; no other config gives null", () => {
    const data = makeTaskRuns({ higher_is_better: false });
    expect(compareTarget(data, RUN_SVM)).toBe(RUN_RF);
    expect(compareTarget({ ...data, groups: data.groups.slice(0, 1) }, RUN_SVM)).toBeNull();
  });
});
