import { expect, test } from "bun:test";
import { commitText, configRows, gpuUse, hostText, placementExtras, statusText } from "../../src/run/props";
import { makeRecord } from "../pages/fixtures";
import { DGX, GPU1, MCCLEARY, NOW, lostRecord, queuedRecord, runningRecord, staleRecord } from "../pages/remoteFixtures";

test("statusText: word, exit code or reason", () => {
  expect(statusText(makeRecord(), "local", null, NOW, null)).toBe("Finished · exit 0");
  expect(statusText(makeRecord({ status: "failed", exit_code: 137 }), "local", null, NOW, null)).toBe("Failed · exit 137");
  expect(statusText(makeRecord({ status: "failed", exit_code: 1, end_reason: "OOM" }), "local", null, NOW, null)).toBe("Failed · exit 1 · OOM");
  expect(statusText(lostRecord(), "lost", MCCLEARY, NOW, null)).toBe("Lost · no exit code");
  expect(statusText(lostRecord(), "lost", MCCLEARY, NOW, "NODE_FAIL on r814u05n01")).toBe("Lost · NODE_FAIL on r814u05n01");
  expect(statusText(staleRecord(), "stale", DGX, NOW, null)).toBe("Stale · dgx unreachable 5m");
  expect(statusText(runningRecord(), "running", GPU1, NOW, null)).toBe("Running");
});

test("hostText and gpuUse", () => {
  expect(hostText(makeRecord(), "local", null)).toBe("mbp.local");
  expect(hostText(makeRecord({ executor: { ...makeRecord().executor, gpus: [2, 5] } }), "local", null)).toBe("mbp.local · GPU 2, 5");
  expect(hostText(runningRecord(), "running", GPU1)).toBe("gpu1 · ssh");
  expect(gpuUse(runningRecord(), "running", GPU1)).toMatch(/^\d+% · \d+ GB$/);
  expect(gpuUse(queuedRecord(), "queued", GPU1)).toBeNull();
});

test("commitText marks a dirty tree and untracked files", () => {
  expect(commitText(makeRecord().git)).toBe("8f4cac4 · untracked");
  expect(commitText({ ...makeRecord().git, dirty: true })).toBe("8f4cac4 · dirty");
  expect(commitText({ ...makeRecord().git, commit: null })).toBeNull();
});

test("configRows: params in order, varying keys and a varying seed tinted", () => {
  const record = makeRecord({ params: { model: "svm", C: "1.0" } });
  expect(configRows(record, ["model"], true)).toEqual([
    { key: "model", value: "svm", varies: true },
    { key: "C", value: "1.0", varies: false },
    { key: "seed", value: "3", varies: true },
  ]);
  expect(configRows(makeRecord({ seed: null }), [], false)).toEqual([]);
});

test("placementExtras: the remote rows the Host and Cost rows do not already show", () => {
  expect(placementExtras(lostRecord(), "lost", MCCLEARY).map((r) => r.key)).toEqual(["Job", "Node", "GPUs"]);
  expect(placementExtras(queuedRecord(), "queued", GPU1).map((r) => [r.key, r.value])).toEqual([["GPUs", "2×A100 80GB"], ["Queue", "2 of 3"]]);
});
