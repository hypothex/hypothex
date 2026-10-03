import { describe, expect, test } from "bun:test";
import { renderHook, waitFor } from "@testing-library/react";
import {
  DEFAULT_STALE_BANNER_HOURS,
  cellTitle,
  fmtAgeMs,
  fmtMoney,
  gpuCells,
  gpuColumns,
  gpuCountLabel,
  gpuSpec,
  hostRowForRun,
  hostTotals,
  hostsHeadline,
  hostsMetaline,
  longStale,
  meanUtil,
  remoteRows,
  shortGpuName,
  staleBannerHours,
  useNow,
} from "../../src/pages/components/HostsPanel";
import type { HostRow } from "../../src/pages/components/types";
import { makeRecord } from "./fixtures";
import { NOW, RUN_AGENT, RUN_HUMAN, RUN_STALE, gpu, localRow, makeHostRuns, makeHosts } from "./hostFixtures";

const runs = new Map(makeHostRuns().map((r) => [r.run_id, r]));
const [gpu1, dgx, mccleary] = makeHosts() as [HostRow, HostRow, HostRow, HostRow];

describe("formatting", () => {
  test("fmtMoney: whole dollars with commas from $10, cents below", () => {
    expect([fmtMoney(106.2), fmtMoney(1234.5), fmtMoney(0.5), fmtMoney(9.999), fmtMoney(0)]).toEqual([
      "$106",
      "$1,235",
      "$0.50",
      "$10.00",
      "$0.00",
    ]);
  });

  test("fmtAgeMs picks the largest whole unit and clamps clock skew to 0s", () => {
    expect([fmtAgeMs(59_000), fmtAgeMs(240_000), fmtAgeMs(7_200_000), fmtAgeMs(172_800_000), fmtAgeMs(-5_000)]).toEqual([
      "59s",
      "4m",
      "2h",
      "2d",
      "0s",
    ]);
  });

  test("shortGpuName drops vendor, form factor and memory tokens", () => {
    expect(shortGpuName("NVIDIA A100-SXM4-80GB")).toBe("A100");
    expect(shortGpuName("NVIDIA H100 80GB HBM3")).toBe("H100");
    expect(shortGpuName("NVIDIA RTX A6000")).toBe("RTX A6000");
    expect(shortGpuName("Tesla V100-SXM2-32GB")).toBe("V100");
    expect(shortGpuName("Fake GPU")).toBe("Fake GPU");
  });

  test("gpuSpec: count × model and size, or a count when GPUs differ", () => {
    expect(gpuSpec(gpu1.gpus)).toBe("5×A100 80GB");
    expect(gpuSpec(dgx.gpus)).toBe("2×H100 80GB");
    expect(gpuSpec([gpu(0), gpu(1, { name: "NVIDIA H100 80GB HBM3" })])).toBe("2 GPUs");
    expect(gpuSpec([])).toBe("");
  });

  test("gpuCountLabel: any count named after a set of GPUs", () => {
    expect(gpuCountLabel(2, gpu1.gpus)).toBe("2×A100 80GB");
    expect(gpuCountLabel(1, [gpu(0), gpu(1, { name: "NVIDIA H100 80GB HBM3" })])).toBe("1 GPU");
    expect(gpuCountLabel(3, [])).toBe("3 GPUs");
  });
});

describe("gpuCells", () => {
  test("one run on adjacent GPUs is one wide cell; launchers decide agent or human", () => {
    const cells = gpuCells(gpu1.gpus, runs);
    expect(cells.map((c) => [c.kind, c.index, c.span, c.runId])).toEqual([
      ["agent", 0, 2, RUN_AGENT],
      ["other", 2, 1, null],
      ["human", 3, 1, RUN_HUMAN],
      ["free", 4, 1, null],
    ]);
    expect(cells[0]?.utils).toEqual([92, 91]);
    expect(cells[0]?.memUsedMb).toBe(61440);
    expect(meanUtil(cells[0]!)).toBe(92);
  });

  test("a run the overview does not list is kind 'run'; input order does not matter", () => {
    const cells = gpuCells([...dgx.gpus].reverse(), runs);
    expect(cells.map((c) => [c.kind, c.index, c.runId])).toEqual([
      ["run", 0, RUN_STALE],
      ["free", 1, null],
    ]);
  });

  test("the same run on GPUs that are not adjacent stays two cells", () => {
    const cells = gpuCells([gpu(0, { run_id: RUN_AGENT }), gpu(2, { run_id: RUN_AGENT })], runs);
    expect(cells.map((c) => [c.index, c.span])).toEqual([
      [0, 1],
      [2, 1],
    ]);
  });

  test("an hx run wins over the external flag", () => {
    const [cell] = gpuCells([gpu(0, { run_id: RUN_HUMAN, external: true })], runs);
    expect(cell?.kind).toBe("human");
  });

  test("cellTitle lists where, run, label, launcher, per-GPU use, and staleness", () => {
    const [agent, other, , free] = gpuCells(gpu1.gpus, runs);
    expect(cellTitle("gpu1", agent!, runs.get(RUN_AGENT), null)).toBe(
      "gpu1 GPU 0–1: 6b0e\nlr 3e-4\nagent:tuner\nGPU 0 92%, GPU 1 91%, 60.0 GB",
    );
    expect(cellTitle("gpu1", other!, undefined, null)).toBe("gpu1 GPU 2: not hx\n63%, 40.0 GB");
    expect(cellTitle("gpu1", free!, undefined, null)).toBe("gpu1 GPU 4: free");
    const [stale] = gpuCells(dgx.gpus, runs);
    expect(cellTitle("dgx", stale!, undefined, "14:27")).toBe("dgx GPU 0: 8e41\nGPU 0 95%, 0.0 GB\nas of 14:27");
  });

  test("gpuColumns is 8 unless a host has a higher GPU index", () => {
    expect(gpuColumns(makeHosts())).toBe(8);
    expect(gpuColumns([{ ...mccleary, gpus: [] }])).toBe(8);
    expect(gpuColumns([{ ...gpu1, gpus: [gpu(11)] }])).toBe(12);
  });
});

describe("totals and headline", () => {
  const totals = hostTotals(makeHosts(), NOW);

  test("hostTotals counts runs, waiting, free GPUs on connected hosts, cost and stale hosts", () => {
    // runs: 6b0e, 52c9, 8e41 (3 distinct) + 4 SLURM; waiting: 3 + 2 + 6 pending
    const { usdToday, ...rest } = totals;
    expect(rest).toEqual({ running: 7, waiting: 11, freeGpus: 1, stale: [{ name: "dgx", age: "4m" }] });
    expect(usdToday).toBeCloseTo(331.6, 9);
  });

  test("hostsHeadline prefers backend counts and falls back to host totals", () => {
    expect(hostsHeadline({ running: 12, queued: 11 }, totals)).toBe("12 running, 11 waiting. dgx stale 4m");
    expect(hostsHeadline({ "runs today": 19 }, totals)).toBe("7 running, 11 waiting. dgx stale 4m");
    expect(hostsHeadline({ running: 2, queued: 0 }, { ...totals, stale: [] })).toBe("2 running.");
    expect(hostsHeadline({ running: 0, queued: 5 }, { ...totals, stale: [] })).toBe("5 waiting.");
    expect(hostsHeadline({ running: 0, queued: 0 }, { ...totals, stale: [] })).toBe("Idle.");
  });

  test("two stale hosts are listed in host order", () => {
    const hosts = makeHosts();
    const gpu2 = hosts[3]!;
    hosts[3] = { ...gpu2, state: { ...gpu2.state, state: "stale", since: "2026-10-03T12:32:00Z" } };
    expect(hostsHeadline({ running: 1, queued: 0 }, hostTotals(hosts, NOW))).toBe(
      "1 running. dgx stale 4m, gpu2 stale 2h",
    );
  });

  test("hostsMetaline: free GPUs, cost today, hub version, host count", () => {
    expect(hostsMetaline(totals, "0.5.0", 4)).toEqual(["1 GPU free", "$332 today", "hub hx 0.5.0", "4 hosts"]);
    expect(hostsMetaline({ ...totals, freeGpus: 0, usdToday: 0 }, null, 1)).toEqual([
      "0 GPUs free",
      "$0.00 today",
      "1 host",
    ]);
  });
});

describe("hosts and runs", () => {
  test("hostRowForRun matches the run's environment, never executor.host", () => {
    const hosts = [localRow(), ...makeHosts()];
    const base = makeRecord();
    // the backend writes the box's own hostname into executor.host, not the hub's host name
    const run = { ...base, environment_id: "env-dgx", host: "dgx-h100-07", executor: { ...base.executor, host: "dgx-h100-07" } };
    expect(hostRowForRun(run, hosts)?.name).toBe("dgx");
    expect(hostRowForRun({ ...run, environment_id: "env-local" }, hosts)?.name).toBe("local");
    expect(hostRowForRun({ ...run, environment_id: "env-elsewhere" }, hosts)).toBeNull();
    expect(hostRowForRun(run, undefined)).toBeNull();
    // an empty environment id never matches (gpu2 has never connected and has none)
    expect(hostRowForRun({ ...run, environment_id: "" }, hosts)).toBeNull();
  });

  test("remoteRows drops the hub's own row", () => {
    expect(remoteRows([localRow(), ...makeHosts()]).map((h) => h.name)).toEqual(["gpu1", "dgx", "mccleary", "gpu2"]);
  });

  test("longStale lists the hosts stale for longer than the banner threshold", () => {
    expect(DEFAULT_STALE_BANNER_HOURS).toBe(24);
    expect(longStale(makeHosts(), NOW)).toEqual([]);
    const hosts = makeHosts();
    const dgx = hosts[1]!;
    // stale for 25 h: past the default 24 h, not past a threshold of 48 h
    const since = new Date(NOW - 25 * 3_600_000).toISOString();
    hosts[1] = { ...dgx, state: { ...dgx.state, since } };
    expect(longStale(hosts, NOW)).toEqual([{ name: "dgx", age: "1d" }]);
    expect(longStale(hosts, NOW, 48)).toEqual([]);
    // stale for 4 min: past a threshold of 0.05 h (3 min)
    expect(longStale(makeHosts(), NOW, 0.05)).toEqual([{ name: "dgx", age: "4m" }]);
  });

  test("staleBannerHours reads the hub's setting from the hosts list, else 24", () => {
    expect(staleBannerHours([])).toBe(24);
    expect(staleBannerHours(makeHosts())).toBe(24);
    expect(staleBannerHours([localRow({ stale_banner_hours: 6 }), ...makeHosts()])).toBe(6);
    // a missing, zero, negative or non-finite value keeps the default
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(staleBannerHours([localRow({ stale_banner_hours: bad })])).toBe(24);
    }
  });
});

test("useNow re-renders with a later time every interval", async () => {
  const { result, unmount } = renderHook(() => useNow(20));
  const first = result.current;
  expect(Math.abs(first - Date.now())).toBeLessThan(1000);
  await waitFor(() => expect(result.current).toBeGreaterThan(first));
  unmount();
});
