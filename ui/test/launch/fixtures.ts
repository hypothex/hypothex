/** Hosts as `GET /api/v1/hosts` returns them, shaped like the phase 2 mockup. */
import type { GpuInfo, HostRow, HostState } from "../../src/api/models";
import type { LaunchHost } from "../../src/launch/plan";

export const PROJECT = "rxn-forward";
export const TASK = "uspto-forward-top1";
export const REPO_PATH = "/Users/sv/code/rxn-forward";
export const CMD = "python train.py --lr 3e-4 --seed {seed}";
/** Shared deterministic reference, matching the pure launch-plan test clock. */
export const FIXTURE_NOW = Date.parse("2026-10-03T14:32:00Z");

export function minutesAgo(minutes: number): string {
  return new Date(FIXTURE_NOW - minutes * 60_000).toISOString();
}

export function gpu(index: number, over: Partial<GpuInfo> = {}): GpuInfo {
  return {
    index,
    name: "A100 80GB",
    util: 0,
    mem_used_mb: 0,
    mem_total_mb: 81920,
    external: false,
    run_id: null,
    ...over,
  };
}

/** One `GET /api/v1/hosts` row; `state` overrides fields of its `HostState`. */
export function hostRow(name: string, over: Partial<HostRow> = {}, state: Partial<HostState> = {}): HostRow {
  const kind = over.kind ?? "ssh";
  return {
    name,
    kind,
    state: {
      name,
      kind,
      state: "connected",
      since: minutesAgo(0),
      message: "",
      environment_id: `env-${name}`,
      hx_version: "0.5.0",
      last_sequence: 0,
      local_port: 41000,
      ...state,
    },
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 0,
    projects: [PROJECT],
    ...over,
  };
}

/** A `LaunchHost` for pure-function tests. */
export function launchHost(over: Partial<LaunchHost> = {}): LaunchHost {
  return {
    name: "gpu1",
    kind: "ssh",
    state: "connected",
    since: null,
    message: "",
    gpus: [],
    queue: 0,
    slurm: null,
    projects: [PROJECT],
    ...over,
  };
}

const busy = (index: number, runId: string, name = "A100 80GB"): GpuInfo =>
  gpu(index, { name, run_id: runId, util: 90, mem_used_mb: 60000 });

/** 8 GPUs: hx runs on 0-2, 4, 6; another user on 3 and 7; GPU 5 free. 3 runs queued. */
export const GPU1 = hostRow("gpu1", {
  queue: 3,
  gpus: [
    busy(0, "r-6b0e"),
    busy(1, "r-6b0e"),
    busy(2, "r-1d77"),
    gpu(3, { external: true, util: 63 }),
    busy(4, "r-52c9"),
    gpu(5),
    busy(6, "r-3fa2"),
    gpu(7, { external: true, util: 9 }),
  ],
});

/** Stale for 4 minutes. The hub sends no GPUs and queue 0 for a host that is not connected. */
export const DGX = hostRow("dgx", {}, { state: "stale", since: minutesAgo(4) });

export const MCCLEARY = hostRow("mccleary", { kind: "slurm", slurm: { pending: 6, running: 4 } });

/** Still installing hx (as the hub sends it: no GPUs yet). */
export const GPU2 = hostRow("gpu2", {}, { state: "bootstrapping" });
