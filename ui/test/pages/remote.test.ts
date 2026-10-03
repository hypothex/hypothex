import { describe, expect, test } from "bun:test";
import {
  costNote,
  fmtWait,
  freeGpus,
  gpuLabel,
  hostLabel,
  lostReason,
  ordinal,
  runHostRow,
  runPhase,
  secondsSince,
  shortGpuName,
  stateTitle,
  sweepCrumb,
  sweepHref,
  visibleDevices,
} from "../../src/pages/components/remote";
import { gpuSpec } from "../../src/pages/components/HostsPanel";
import type { HostRow } from "../../src/pages/components/types";
import { COST, HOSTS } from "../api/phase2-fixtures";
import { makeDetail, makeRecord } from "./fixtures";
import {
  DGX,
  GPU1,
  MCCLEARY,
  NOW,
  lostRecord,
  pendingRecord,
  queuedRecord,
  remoteDetail,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

describe("runPhase", () => {
  test("hub runs keep the phase 1 layout; remote runs get a phase", () => {
    expect(runPhase(makeDetail())).toBe("local");
    expect(runPhase(makeDetail({ status: "queued" }))).toBe("local");
    expect(runPhase(remoteDetail(queuedRecord()))).toBe("queued");
    expect(runPhase(remoteDetail(pendingRecord()))).toBe("pending");
    expect(runPhase(remoteDetail(runningRecord()))).toBe("running");
    expect(runPhase(remoteDetail(lostRecord()))).toBe("lost");
    expect(runPhase(remoteDetail(runningRecord({ status: "finished" })))).toBe("ended");
  });

  test("an active run on a host the hub cannot reach is stale, never lost", () => {
    expect(runPhase(remoteDetail(staleRecord(), "stale"))).toBe("stale");
    expect(runPhase(remoteDetail(staleRecord(), "error"))).toBe("stale");
    expect(runPhase(remoteDetail(staleRecord(), "disabled"))).toBe("stale");
    expect(runPhase(remoteDetail(queuedRecord(), "connecting"))).toBe("stale");
    // a finished run stays finished on a stale host
    expect(runPhase(remoteDetail(staleRecord({ status: "finished" }), "stale"))).toBe("ended");
    // the env server decided lost: lost wins even on a hub run
    expect(runPhase(makeDetail({ status: "lost" }))).toBe("lost");
  });

  test("host_state null is a hub run, although the backend sets executor.host on every run", () => {
    const hubRun = makeRecord({ status: "running", executor: { ...makeRecord().executor, host: "mbp.local" } });
    expect(runPhase(makeDetail(hubRun, { host_state: null }))).toBe("local");
    expect(runPhase(remoteDetail(runningRecord(), null))).toBe("local");
  });
});

test("runHostRow matches the run's environment, never executor.host", () => {
  const queued = queuedRecord();
  expect(queued.executor.host).toBe("sv-a100-01");
  expect(runHostRow(remoteDetail(queued), HOSTS)).toBe(GPU1);
  expect(runHostRow(remoteDetail(staleRecord(), "stale"), HOSTS)).toBe(DGX);
  expect(runHostRow(remoteDetail(queued), undefined)).toBeNull();
  expect(runHostRow(remoteDetail(queuedRecord({ environment_id: "env-gone" })), HOSTS)).toBeNull();
  // a hub run has no host row, even though its environment is the hub's `local` row
  expect(runHostRow(makeDetail({ environment_id: "env-hub" }, { host_state: null }), HOSTS)).toBeNull();
  expect(hostLabel(queued, GPU1)).toBe("gpu1");
  expect(hostLabel(queued, null)).toBe("sv-a100-01");
});

test("ordinal uses st, nd, rd, except for 11 to 13", () => {
  expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112].map(ordinal)).toEqual([
    "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th", "112th",
  ]);
});

test("fmtWait shows seconds, then minutes, then hours and minutes", () => {
  expect([-5, 0, 59.9, 60, 3599, 3600, 6720].map(fmtWait)).toEqual([
    "0s", "0s", "59s", "1m", "59m", "1h 0m", "1h 52m",
  ]);
  expect(secondsSince("2026-10-03T14:21:04Z", NOW)).toBe(776);
  expect(secondsSince("2026-10-03T15:00:00Z", NOW)).toBe(0);
  expect(secondsSince("not a time", NOW)).toBeNull();
});

test("GPU texts: devices, model names, free count", () => {
  expect(visibleDevices([0, 1])).toBe("CUDA_VISIBLE_DEVICES=0,1");
  expect(shortGpuName("NVIDIA A100 80GB PCIe")).toBe("A100");
  expect(shortGpuName("NVIDIA A100-SXM4-80GB")).toBe("A100");
  expect(shortGpuName("Tesla V100")).toBe("V100");
  expect(shortGpuName("H100")).toBe("H100");
  expect(gpuLabel(2, GPU1)).toBe("2×A100 80GB");
  expect(gpuLabel(1, GPU1, [0])).toBe("1×A100 80GB");
  expect(gpuLabel(2, MCCLEARY, [0, 1])).toBe("2 GPUs");
  expect(gpuLabel(2, null)).toBe("2 GPUs");
  expect(gpuLabel(1, null)).toBe("1 GPU");
  const mixed: HostRow = {
    ...GPU1,
    gpus: GPU1.gpus.map((g) => (g.index === 1 ? { ...g, name: "NVIDIA H100" } : g)),
  };
  expect(gpuLabel(2, mixed, [0, 1])).toBe("2 GPUs");
  expect(gpuLabel(1, mixed, [1])).toBe("1×H100 80GB");
  // one GPU, one name: the run page and the hosts grid agree
  expect(gpuLabel(GPU1.gpus.length, GPU1)).toBe(gpuSpec(GPU1.gpus));
  expect(freeGpus(GPU1)).toBe(1);
  expect(freeGpus(DGX)).toBe(0);
});

describe("stateTitle", () => {
  test("names the state after the label", () => {
    expect(stateTitle("lr 1e-3", "queued", queuedRecord(), GPU1)).toBe("lr 1e-3: queued 2nd on gpu1");
    expect(stateTitle("seed 3", "pending", pendingRecord(), MCCLEARY)).toBe("seed 3: pending on mccleary");
    expect(stateTitle("beam 10", "stale", staleRecord(), DGX)).toBe("beam 10: stale since 14:28");
    expect(stateTitle("seed 2", "lost", lostRecord(), MCCLEARY)).toBe("seed 2: lost at 02:14");
    expect(stateTitle("seed 2", "lost", lostRecord({ ended_at: null }), null)).toBe("seed 2: lost");
  });

  test("running, ended and hub runs keep their title", () => {
    expect(stateTitle("x", "running", runningRecord(), GPU1)).toBeNull();
    expect(stateTitle("x", "ended", runningRecord({ status: "finished" }), GPU1)).toBeNull();
    expect(stateTitle("x", "local", makeRecord(), null)).toBeNull();
  });

  test("without the hosts list or a queue position", () => {
    // no hosts list: the machine's own hostname, never a guess at the hub's name
    expect(stateTitle("beam 10", "stale", staleRecord(), null)).toBe("beam 10: dgx-h100-07 unreachable");
    expect(stateTitle("lr 1e-3", "queued", queuedRecord(), null)).toBe("lr 1e-3: queued 2nd on sv-a100-01");
    const unplaced = queuedRecord({ executor: { ...queuedRecord().executor, queue_position: null } });
    expect(stateTitle("lr 1e-3", "queued", unplaced, GPU1)).toBe("lr 1e-3: queued on gpu1");
  });
});

test("lostReason names what the record says, in neutral words, never a guessed cause", () => {
  // a SLURM job can be lost to NODE_FAIL while still in sacct: no "left squeue and sacct"
  expect(lostReason(lostRecord())).toEqual({
    title: "SLURM job 4471023 lost",
    tooltip: "The env server marked this run lost. Its run.lost event has the reason.",
    parts: ["r814u05n01", "02:14:37 UTC", "no exit code"],
  });
  const local = makeRecord({ status: "lost", ended_at: "2026-10-03T09:00:05Z", exit_code: null });
  expect(lostReason(local)).toEqual({
    title: "run lost",
    tooltip: "The env server marked this run lost. Its run.lost event has the reason.",
    parts: ["09:00:05 UTC", "no exit code"],
  });
  expect(lostReason(makeRecord({ status: "lost", ended_at: null, exit_code: 137 })).parts).toEqual(["exit 137"]);
});

test("lostReason shows the env server's run.lost reason first when it is known", () => {
  const why = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";
  expect(lostReason(lostRecord(), why)).toEqual({
    title: "SLURM job 4471023 lost",
    tooltip: "Reason from the run's run.lost event.",
    parts: [why, "r814u05n01", "02:14:37 UTC", "no exit code"],
  });
  // a blank or missing reason keeps the neutral words
  expect(lostReason(lostRecord(), "  ")).toEqual(lostReason(lostRecord()));
  expect(lostReason(lostRecord(), null)).toEqual(lostReason(lostRecord()));
});

test("sweepHref encodes; costNote shows GPU hours and API dollars", () => {
  expect(sweepHref("my proj", "s-7f3a")).toBe("/s/my%20proj/s-7f3a");
  expect(costNote(COST)).toBe("3.50 GPU h, API $0.42");
});

test("sweepCrumb links only a sweep this hub owns (its owner-qualified tag)", () => {
  const hub = "0a1b2c3d4e5f60718293a4b5c6d7e8f9";
  const mine = lostRecord({ tags: ["best", "sweep:0a1b2c3d:s-7f3a"] });
  expect(sweepCrumb(mine, hub)).toEqual({ id: "s-7f3a", href: "/s/toy-classifier/s-7f3a", why: null });
  // a shared host: another hub launched this sweep, so this hub has no page for it
  expect(sweepCrumb(lostRecord({ tags: ["sweep:ffffffff:s-7f3a"] }), hub)).toEqual({
    id: "s-7f3a",
    href: null,
    why: "sweep of another hub (ffffffff)",
  });
  // only the tag of the run's own sweep id counts; none at all is plain text too
  const other = { id: "s-7f3a", href: null, why: "no sweep tag on this run" };
  expect(sweepCrumb(lostRecord({ tags: ["sweep:0a1b2c3d:s-0000"] }), hub)).toEqual(other);
  expect(sweepCrumb(lostRecord({ tags: [] }), hub)).toEqual(other);
  // the hub's id not known yet (descriptor loading or failed): plain text, no reason
  expect(sweepCrumb(mine, null)).toEqual({ id: "s-7f3a", href: null, why: null });
  expect(sweepCrumb(runningRecord(), hub)).toBeNull();
});
