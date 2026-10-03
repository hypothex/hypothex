/** Hosts fixtures for the Hosts panel and Overview tests (mockup `shot-overview-*`). */
import type { GpuInfo, HostRow, RunRecord } from "../../src/pages/components/types";
import { makeRecord } from "./fixtures";

/** 2026-10-03 14:32 UTC, the mockup's "now". */
export const NOW = Date.parse("2026-10-03T14:32:00Z");
export const RUN_AGENT = "20261003-140102-uspto-6b0e";
export const RUN_HUMAN = "20261003-131500-uspto-52c9";
/** On the stale host; not in the overview's running list. */
export const RUN_STALE = "20261003-120000-uspto-8e41";

const A100 = "NVIDIA A100-SXM4-80GB";
const H100 = "NVIDIA H100 80GB HBM3";

export function gpu(index: number, over: Partial<GpuInfo> = {}): GpuInfo {
  return {
    index,
    name: A100,
    util: 0,
    mem_used_mb: 0,
    mem_total_mb: 81920,
    external: false,
    run_id: null,
    ...over,
  };
}

function state(
  name: string,
  kind: HostRow["kind"],
  conn: HostRow["state"]["state"],
  since: string,
  over: Partial<HostRow["state"]> = {},
): HostRow["state"] {
  return {
    name,
    kind,
    state: conn,
    since,
    message: "",
    environment_id: `env-${name}`,
    hx_version: "0.5.0",
    last_sequence: 0,
    local_port: null,
    ...over,
  };
}

/** The hub's own row: `GET /api/v1/hosts` always lists it first. */
export function localRow(over: Partial<HostRow> = {}): HostRow {
  return {
    name: "local",
    kind: "local",
    state: state("local", "local", "connected", "2026-10-03T08:00:00Z"),
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 0,
    projects: ["rxn-forward"],
    ...over,
  };
}

/** `rows` as the hub sends them: a host that is not connected has no GPUs and queue 0. */
export function asSent(rows: HostRow[]): HostRow[] {
  return rows.map((r) => (r.state.state === "connected" ? r : { ...r, gpus: [], queue: 0 }));
}

/**
 * Four hosts, as the panel draws them (`useHosts` has kept dgx's last known cells): gpu1
 * (connected, hx 0.4.1, agent run on GPUs 0-1, not-hx GPU 2, human run on GPU 3, GPU 4
 * free, queue 3), dgx (stale since `now` − 4 min, last known: one run, one free GPU, queue
 * 2), mccleary (SLURM, 4 running, 6 pending), gpu2 (bootstrapping, no GPUs yet).
 */
export function makeHosts(now: number = NOW): HostRow[] {
  const staleSince = new Date(now - 4 * 60_000 - 5_000).toISOString();
  return [
    {
      name: "gpu1",
      kind: "ssh",
      state: state("gpu1", "ssh", "connected", "2026-10-03T09:00:00Z", { hx_version: "0.4.1" }),
      gpus: [
        gpu(0, { run_id: RUN_AGENT, util: 92, mem_used_mb: 30720 }),
        gpu(1, { run_id: RUN_AGENT, util: 91, mem_used_mb: 30720 }),
        gpu(2, { external: true, util: 63, mem_used_mb: 40960 }),
        gpu(3, { run_id: RUN_HUMAN, util: 77, mem_used_mb: 20480 }),
        gpu(4),
      ],
      queue: 3,
      slurm: null,
      cost_today_usd: 106.2,
      projects: ["rxn-forward"],
      usd_per_gpu_hour: 1.1,
    },
    {
      name: "dgx",
      kind: "ssh",
      state: state("dgx", "ssh", "stale", staleSince),
      gpus: [gpu(0, { name: H100, run_id: RUN_STALE, util: 95 }), gpu(1, { name: H100 })],
      queue: 2,
      slurm: null,
      cost_today_usd: 206,
      projects: [],
      usd_per_gpu_hour: 2.9,
    },
    {
      name: "mccleary",
      kind: "slurm",
      state: state("mccleary", "slurm", "connected", "2026-10-03T08:00:00Z"),
      gpus: [],
      queue: 0,
      slurm: { pending: 6, running: 4 },
      cost_today_usd: 19.4,
      projects: [],
      usd_per_gpu_hour: 0.5,
    },
    {
      name: "gpu2",
      kind: "ssh",
      state: state("gpu2", "ssh", "bootstrapping", "2026-10-03T14:31:00Z", {
        hx_version: null,
        environment_id: null,
        message: "3/5 uv, hx 0.5.0",
      }),
      gpus: [],
      queue: 0,
      slurm: null,
      cost_today_usd: 0,
      projects: [],
    },
  ];
}

/** The active runs the overview lists for the cells on gpu1. */
export function makeHostRuns(): RunRecord[] {
  return [
    makeRecord({ run_id: RUN_AGENT, created_by: "agent:tuner", hypothesis: "lr 3e-4, beam 10", status: "running" }),
    makeRecord({ run_id: RUN_HUMAN, created_by: "human:shreyas", hypothesis: "+aug long, 40k steps", status: "running" }),
  ];
}
