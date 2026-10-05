import { expect, test } from "bun:test";
import { remoteStats } from "../../src/pages/components/remoteStats";
import { runStats } from "../../src/pages/components/runStats";
import type { StatItem } from "../../src/pages/components/StatStrip";
import { COST } from "../api/phase2-fixtures";
import { makeDetail, makeRecord } from "./fixtures";
import {
  DGX,
  GPU1,
  MCCLEARY,
  NOW,
  lostRecord,
  pendingRecord,
  queuedRecord,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

const show = (items: StatItem[]) => items.map((s) => [s.label, s.value, s.unit ?? null]);

test("remoteStats for a queued run: position, needs, free GPUs, waiting", () => {
  expect(show(remoteStats(queuedRecord(), "queued", GPU1, NOW))).toEqual([
    ["position", "2", "/ 3"],
    ["needs", "2", "GPU"],
    ["free on gpu1", "1", "/ 3"],
    ["waiting", "12m", null],
  ]);
});

test("remoteStats without the hosts list", () => {
  expect(show(remoteStats(queuedRecord(), "queued", null, NOW))).toEqual([
    ["position", "2", null],
    ["needs", "2", "GPU"],
    ["waiting", "12m", null],
  ]);
  expect(show(remoteStats(staleRecord(), "stale", null, NOW))).toEqual([["GPU h", "7.00", null]]);
});

test("remoteStats for a SLURM job still pending", () => {
  expect(show(remoteStats(pendingRecord(), "pending", MCCLEARY, NOW))).toEqual([
    ["needs", "2", "GPU"],
    ["job", "4471031", null],
    ["waiting", "4m", null],
  ]);
});

test("remoteStats for a running run: GPU use, memory, GPU hours so far", () => {
  const items = remoteStats(runningRecord(), "running", GPU1, NOW);
  expect(show(items)).toEqual([
    ["GPU", "92", "%"],
    ["mem", "57", "GB"],
    ["GPU h", "1.87", null],
  ]);
  expect(items[0]?.tooltip).toBe("mean utilization of GPU 0");
  // once the cost is set it is the run's own number; GPU hours are in its tooltip
  expect(show(remoteStats(runningRecord({ cost: COST }), "running", GPU1, NOW))).toEqual([
    ["GPU", "92", "%"],
    ["mem", "57", "GB"],
  ]);
});

test("remoteStats on SLURM never reads the login node's GPUs for the job's GPU use", () => {
  // the job's GPU indices are on its compute node; the host row's GPUs are the login node's
  const job = runningRecord({
    environment_id: "env-mccleary",
    executor: { ...runningRecord().executor, type: "slurm", host: "mccleary-login1", slurm_job_id: "4471031", gpus: [0] },
  });
  const login = { ...MCCLEARY, gpus: GPU1.gpus };
  expect(show(remoteStats(job, "running", login, NOW)).map(([label]) => label)).toEqual(["GPU h"]);
});

test("remoteStats for a stale run: GPU hours and how long the host is gone", () => {
  expect(show(remoteStats(staleRecord(), "stale", DGX, NOW))).toEqual([
    ["GPU h", "7.00", null],
    ["unreachable", "5m", null],
  ]);
});

test("remoteStats is empty for hub and ended runs", () => {
  expect(remoteStats(makeRecord(), "local", null, NOW)).toEqual([]);
  expect(remoteStats(lostRecord(), "lost", MCCLEARY, NOW)).toEqual([]);
  expect(remoteStats(runningRecord({ status: "finished" }), "ended", GPU1, NOW)).toEqual([]);
});

test("host clock ahead of the hub: GPU hours and waiting read 0, never negative", () => {
  // the host stamped started_at / created_at 10 minutes after the hub's now
  const started = runningRecord({ started_at: "2026-10-03T14:44:00Z" });
  expect(show(remoteStats(started, "running", GPU1, NOW))).toEqual([
    ["GPU", "92", "%"],
    ["mem", "57", "GB"],
    ["GPU h", "0.00", null],
  ]);
  const queued = queuedRecord({ created_at: "2026-10-03T14:44:00Z" });
  expect(show(remoteStats(queued, "queued", GPU1, NOW)).at(-1)).toEqual(["waiting", "0s", null]);
});

test("runStats shows the run's cost once, with what it is made of in the tooltip", () => {
  const usage = { tokens_in: 153000, tokens_out: 4500, usd: 0.25, seconds: 68.4, calls: 13 };
  const both = runStats(makeDetail({ usage, cost: COST }), null, null);
  expect(both.map((s) => [s.label, s.value])).toEqual([
    ["wall", "0.8 s"],
    ["tokens in", "153k"],
    ["tokens out", "4.5k"],
    ["cost", "$2.17"],
  ]);
  expect(both.find((s) => s.label === "cost")?.tooltip).toBe("3.50 GPU h, API $0.42");
  const lost = runStats(makeDetail(lostRecord()), null, null, NOW);
  expect(lost.map((s) => [s.label, s.value])).toEqual([
    ["wall", "52m 27s"],
    ["cost", "$2.17"],
  ]);
  // no cost on the record: the usage cost, as in phase 1b
  const old = runStats(makeDetail({ usage }), null, null);
  expect(old.find((s) => s.label === "cost")).toEqual({ label: "cost", value: "$0.25", tooltip: "13 calls" });
});

test("runStats shows no cost for an all-zero cost, and `—` for GPU hours with no rate", () => {
  const zero = { gpu_hours: 0, gpu_usd: 0, api_usd: 0, total_usd: 0 };
  expect(runStats(makeDetail({ cost: zero }), null, null).map((s) => s.label)).toEqual(["wall"]);
  // usage with zero dollars: the phase 1b usage cost, not the zero cost
  const usage = { tokens_in: 10, tokens_out: 2, usd: 0, seconds: 1, calls: 1 };
  const withUsage = runStats(makeDetail({ usage, cost: zero }), null, null);
  expect(withUsage.find((s) => s.label === "cost")).toEqual({ label: "cost", value: "$0.000", tooltip: "1 calls" });
  const unpriced = { gpu_hours: 1.5, gpu_usd: 0, api_usd: 0.42, total_usd: 0.42 };
  const stat = runStats(makeDetail({ cost: unpriced }), null, null, NOW, { ...GPU1, usd_per_gpu_hour: null });
  expect(stat.find((s) => s.label === "cost")).toEqual({
    label: "cost",
    value: "—",
    tooltip: "1.50 GPU h, API $0.42, no GPU rate for this host",
  });
});

test("runStats shows the total when no host row says the rate is missing", () => {
  const cost = (items: StatItem[]) => items.find((s) => s.label === "cost");
  const zeroGpuUsd = { gpu_hours: 1.5, gpu_usd: 0, api_usd: 0.42, total_usd: 0.42 };
  const total = { label: "cost", value: "$0.42", tooltip: "1.50 GPU h, API $0.42" };
  // without the hosts list nothing says the rate is missing
  expect(cost(runStats(makeDetail({ cost: zeroGpuUsd }), null, null, NOW))).toEqual(total);
  // explicitly free GPUs (rate 0), and a field an older hub does not send
  expect(cost(runStats(makeDetail({ cost: zeroGpuUsd }), null, null, NOW, { ...GPU1, usd_per_gpu_hour: 0 }))).toEqual(
    total,
  );
  const { usd_per_gpu_hour: _, ...noField } = GPU1;
  expect(cost(runStats(makeDetail({ cost: zeroGpuUsd }), null, null, NOW, noField))).toEqual(total);
  // a tiny charge rounded to 0 at a set rate
  const tiny = { gpu_hours: 0.000001, gpu_usd: 0, api_usd: 0, total_usd: 0 };
  expect(
    cost(runStats(makeDetail({ cost: tiny }), null, null, NOW, { ...GPU1, usd_per_gpu_hour: 0.1 })),
  ).toMatchObject({ value: "$0.000" });
});

test("live SLURM GPU hours use requested GPUs when the node has no indices", () => {
  const base = runningRecord({
    started_at: new Date(NOW - 3_600_000).toISOString(),
    cost: null,
    gpus_requested: 2,
  });
  const record = { ...base, executor: { ...base.executor, slurm_job_id: "42", gpus: [] } };
  for (const phase of ["running", "stale"] as const) {
    const stats = remoteStats(record, phase, MCCLEARY, NOW);
    expect(stats.find((s) => s.label === "GPU h")).toMatchObject({ value: "2.00" });
    expect(stats.some((s) => s.label === "GPU" || s.label === "mem")).toBe(false);
  }
  const cpu = { ...record, gpus_requested: 0 };
  expect(remoteStats(cpu, "running", MCCLEARY, NOW).some((s) => s.label === "GPU h")).toBe(false);
  const local = { ...record, executor: { ...record.executor, slurm_job_id: null } };
  expect(remoteStats(local, "running", GPU1, NOW).some((s) => s.label === "GPU h")).toBe(false);
});
