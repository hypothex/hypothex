/**
 * Phase 2 API bodies for the api tests (phase 2 contract sections 1.5-1.7 and 2).
 *
 * Typed against `src/api/models.ts`, so `bun run typecheck` fails when a model drifts
 * from the contract. Numbers are invented but consistent: gpu1 has 3 GPUs (one held by
 * run r-6b0e, one by a process outside hx, one free); the sweep grid is 3 lr values x 1
 * beam x 3 seeds, with 6 runs so far: the third lr value came from an extend that has not
 * launched yet, so its cell has no runs and no group (`group_id: null`, as the backend
 * sends it). `HOSTS` is shaped like the backend's `host_rows`: the hub's own
 * `local` row first, and no GPUs or queue for a host that is not connected (dgx is stale).
 * Every row carries the hub's `stale_banner_hours` (default 24, controller ruling R1).
 */
import type {
  CostTotals,
  ExecutorInfo,
  HostLaunchRequest,
  HostRow,
  HostState,
  LeaderboardRow,
  OverviewSummary,
  SweepCell,
  SweepListItem,
  SweepSummary,
} from "../../src/api/models";

export const GPU1_STATE: HostState = {
  name: "gpu1",
  kind: "ssh",
  state: "connected",
  since: "2026-10-03T14:00:00Z",
  message: "",
  environment_id: "env-gpu1",
  hx_version: "0.5.0",
  last_sequence: 412,
  local_port: 51234,
};

export const DGX_STATE: HostState = {
  name: "dgx",
  kind: "ssh",
  state: "stale",
  since: "2026-10-03T14:28:02Z",
  message: "no ping for 60 s",
  environment_id: "env-dgx",
  hx_version: "0.5.0",
  last_sequence: 97,
  local_port: 51240,
};

const A100 = "NVIDIA A100 80GB PCIe";

/** The hub's own row: `host_rows` always lists it first, `kind: "local"`, always connected. */
export const LOCAL_ROW: HostRow = {
  name: "local",
  kind: "local",
  state: {
    name: "local",
    kind: "local",
    state: "connected",
    since: "2026-10-03T08:00:00Z",
    message: "",
    environment_id: "env-hub",
    hx_version: "0.5.0",
    last_sequence: 1022,
    local_port: null,
  },
  gpus: [],
  queue: 0,
  slurm: null,
  cost_today_usd: 0,
  usd_per_gpu_hour: null,
  stale_banner_hours: 24,
  projects: ["toy"],
};

export const HOSTS: HostRow[] = [
  LOCAL_ROW,
  {
    name: "gpu1",
    kind: "ssh",
    state: GPU1_STATE,
    gpus: [
      { index: 0, name: A100, util: 92, mem_used_mb: 58_112, mem_total_mb: 81_920, external: false, run_id: "r-6b0e" },
      { index: 1, name: A100, util: 63, mem_used_mb: 33_587, mem_total_mb: 81_920, external: true, run_id: null },
      { index: 2, name: A100, util: 0, mem_used_mb: 4, mem_total_mb: 81_920, external: false, run_id: null },
    ],
    queue: 3,
    slurm: null,
    cost_today_usd: 106.04,
    usd_per_gpu_hour: 1.1,
    stale_banner_hours: 24,
    projects: ["toy"],
  },
  {
    name: "mccleary",
    kind: "slurm",
    state: {
      ...GPU1_STATE,
      name: "mccleary",
      kind: "slurm",
      environment_id: "env-mccleary",
      last_sequence: 230,
      local_port: 51236,
    },
    gpus: [],
    queue: 0,
    slurm: { pending: 6, running: 4 },
    cost_today_usd: 19,
    usd_per_gpu_hour: 0.5,
    stale_banner_hours: 24,
    projects: ["toy"],
  },
  {
    // stale: the hub asks a host for GPUs and queue only while it is connected
    name: "dgx",
    kind: "ssh",
    state: DGX_STATE,
    gpus: [],
    queue: 0,
    slurm: null,
    cost_today_usd: 206.48,
    usd_per_gpu_hour: 2.9,
    stale_banner_hours: 24,
    projects: [],
  },
];

/**
 * A launch on a host: the project by name and the pinned commit, never a path on this
 * machine (the hub finds its own checkout and the host's mapped one).
 */
export const HOST_LAUNCH: HostLaunchRequest = {
  project: "toy",
  task: "acc",
  command: ["python", "train.py", "--seed", "{seed}"],
  hypothesis: "seed noise of the baseline",
  seed: 4,
  gpus: 1,
  queue: true,
  commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
};

/** The Overview's cost fields (contract section 2, spec 8A.7). */
export const OVERVIEW_COST: Pick<OverviewSummary, "cost_usd" | "cost_today_usd"> = {
  cost_usd: 512.3,
  cost_today_usd: 402.75,
};

/** A leaderboard row's cost: the sum over the group's runs. */
export const BOARD_ROW_COST: Pick<LeaderboardRow, "cost"> = {
  cost: { gpu_hours: 10.5, gpu_usd: 5.25, api_usd: 1.26, total_usd: 6.51 },
};

/**
 * A SLURM run's executor with every phase 2 field set. `host` is the env server's own
 * hostname (`socket.gethostname()` on the login node), not the hub's name for the host.
 */
export const REMOTE_EXECUTOR: ExecutorInfo = {
  type: "slurm",
  pid: null,
  pid_create_time: null,
  child_pid: null,
  host: "mccleary-login1",
  gpus: [0, 1],
  slurm_job_id: "4471023",
  node: "r814u05n01",
  queue_position: null,
};

/** A phase 1 record's executor: the phase 2 fields are absent, and that still type-checks. */
export const PHASE1_EXECUTOR: ExecutorInfo = {
  type: "local",
  pid: 4242,
  pid_create_time: 1_759_500_000.5,
  child_pid: 4243,
};

export const COST: CostTotals = { gpu_hours: 3.5, gpu_usd: 1.75, api_usd: 0.42, total_usd: 2.17 };

export const BEST_CELL: SweepCell = {
  params: { lr: "3e-4", beam: "10" },
  group_id: "g-7e3f",
  n: 3,
  mean: 0.9121,
  lo: 0.9109,
  hi: 0.9133,
  run_ids: ["r-7e3f", "r-f0a1", "r-66cd"],
};

export const SWEEP: SweepSummary = {
  spec: {
    id: "s-7f3a",
    project: "toy",
    task: "acc",
    host: "gpu1",
    grid: [
      { name: "lr", values: ["1e-4", "3e-4", "1e-3"], low: null, high: null, log: false },
      { name: "beam", values: ["10"], low: null, high: null, log: false },
    ],
    random: null,
    seeds: [1, 2, 3],
    command_template: ["python", "train.py", "--lr", "{lr}", "--beam", "{beam}", "--seed", "{seed}"],
    created_by: "agent:tuner",
    created_at: "2026-10-03T09:12:00Z",
  },
  run_ids: ["r-7e3f", "r-f0a1", "r-66cd", "r-71f2", "r-1d77", "r-c2b9"],
  tag: "sweep:0a1b2c3d:s-7f3a",
  counts: { finished: 4, running: 1, queued: 1, failed: 0, killed: 0, lost: 0, total: 6 },
  cells: [
    BEST_CELL,
    {
      params: { lr: "1e-4", beam: "10" },
      group_id: "g-71f2",
      n: 1,
      mean: 0.8979,
      lo: null,
      hi: null,
      run_ids: ["r-71f2", "r-1d77", "r-c2b9"],
    },
    {
      params: { lr: "1e-3", beam: "10" },
      group_id: null,
      n: 0,
      mean: null,
      lo: null,
      hi: null,
      run_ids: [],
    },
  ],
  best: BEST_CELL,
  headline: "lr 3e-4, beam 10: 0.912 [0.911, 0.913], n = 3",
  total_usd: 312.4,
};

export const SWEEP_LIST: SweepListItem[] = [
  { id: "s-7f3a", created_at: "2026-10-03T09:12:00Z", n_runs: 6, best: BEST_CELL },
];
