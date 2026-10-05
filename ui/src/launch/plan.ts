/**
 * Launch targets for the dialog: the hub plus every host from `GET /api/v1/hosts`, whether
 * each can take a run of this project, and how many seeds start now, wait in the hx queue,
 * or cannot start (spec 8A.5).
 */
import type { ConnState, GpuInfo, HostRow, SlurmDefaults } from "../api/models";

export type LaunchHostKind = "hub" | "ssh" | "slurm";

/** Name of the hub's own row; reserved in `environments.yaml`. */
export const HUB = "local";
/** Most GPUs one SLURM job may ask for in the dialog. */
export const SLURM_MAX_GPUS = 8;

export interface LaunchHost {
  name: string;
  environment_id?: string | null;
  kind: LaunchHostKind;
  state: ConnState;
  since: string | null;
  message: string;
  gpus: GpuInfo[];
  /** hx runs waiting for GPUs on this host. */
  queue: number;
  slurm: { pending: number; running: number; defaults?: SlurmDefaults } | null;
  /** Projects with a repo mapped on the host; `null` means every project (the hub). */
  projects: string[] | null;
}

/** The hub's own GPUs (`GET /api/v1/gpus`) and queue length (`GET /api/v1/queue`). */
export interface HubLoad {
  gpus: GpuInfo[];
  queue: number;
}

export interface SlurmFields {
  partition: string;
  account: string;
  time: string;
}

/** Everything one launch needs except the seed. */
export interface LaunchSpec {
  host: LaunchHost;
  /** Sent by name to a host launch (`POST /api/v1/hosts/{host}/runs`). */
  project: string;
  /** The hub's checkout (`TaskDetail.repo`): sent only to the hub, and the CLI's `--repo`. */
  repo: string;
  /** Pinned commit (spec 8A.4); null: the hub pins its own checkout's HEAD and diff. */
  commit: string | null;
  task: string | null;
  argv: string[];
  hypothesis: string;
  gpus: number;
  queue: boolean;
  slurm: SlurmFields | null;
  params: Record<string, string>;
  vars: Record<string, string>;
}

export interface Availability {
  ok: boolean;
  /** Why the host cannot take the run, with the fix; `""` when it can. */
  reason: string;
}

export interface LaunchPlan {
  /** Seeds that start at once. */
  now: number;
  /** Seeds that wait in the hx queue (SSH, queue on) or in SLURM. */
  queued: number;
  /** Seeds that would be refused (queue off or the hub, too few free GPUs). */
  blocked: number;
  /** GPU indices the first seed gets. */
  cvd: number[];
  /** Queue position of the first waiting seed. */
  firstPos: number | null;
}

export type GpuCell = "busy" | "free" | "other" | "stale" | "none";

function fromRow(row: HostRow): LaunchHost {
  return {
    name: row.name,
    environment_id: row.state.environment_id,
    kind: row.kind === "local" ? "hub" : row.kind,
    state: row.state.state,
    since: row.state.since,
    message: row.state.message,
    gpus: row.gpus,
    queue: row.queue,
    slurm: row.slurm,
    projects: row.projects,
  };
}

/** The hub first (its own row if listed, else built from `hub`), then the other hosts in order. */
export function toLaunchHosts(rows: readonly HostRow[], hub: HubLoad): LaunchHost[] {
  const own = rows.find((r) => r.name === HUB);
  const first: LaunchHost = own
    ? { ...fromRow(own), kind: "hub", projects: null }
    : {
        name: HUB,
        kind: "hub",
        state: "connected",
        since: null,
        message: "",
        gpus: hub.gpus,
        queue: hub.queue,
        slurm: null,
        projects: null,
      };
  return [first, ...rows.filter((r) => r.name !== HUB).map(fromRow)];
}

/** `4m`, `1h`, `3d` since an ISO time; `""` when unknown. */
export function ago(since: string | null, now: number): string {
  if (since === null) return "";
  const t = Date.parse(since);
  if (Number.isNaN(t)) return "";
  const minutes = Math.max(0, Math.round((now - t) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`;
  return `${Math.floor(minutes / 1440)}d`;
}

const STATE_LABEL: Record<ConnState, string> = {
  connecting: "connecting",
  bootstrapping: "boot",
  connected: "connected",
  stale: "stale",
  upgrade: "upgrade",
  error: "error",
  disabled: "off",
};

/** The short state text for a host row. */
export function stateLabel(host: LaunchHost, now: number): string {
  if (host.state === "stale") {
    const age = ago(host.since, now);
    return age ? `stale ${age}` : "stale";
  }
  return STATE_LABEL[host.state];
}

/** Why a host in this state cannot take a run, with the fix. */
export function stateReason(host: LaunchHost, now: number): string {
  const name = host.name;
  switch (host.state) {
    case "connected":
      return "";
    case "stale": {
      const age = ago(host.since, now);
      return age ? `${name} stale ${age}: no heartbeat` : `${name} stale: no heartbeat`;
    }
    case "connecting":
      return `connecting to ${name}`;
    case "bootstrapping":
      return host.message ? `installing hx on ${name}: ${host.message}` : `installing hx on ${name}`;
    case "upgrade":
      return `hx on ${name} needs an upgrade: hx hosts upgrade ${name}`;
    case "error":
      return host.message || `${name}: connection error`;
    case "disabled":
      return `${name} disconnected: hx hosts connect ${name}`;
  }
}

/** A host can take the run when it is connected and has this project's repo mapped (8A.4). */
export function availability(host: LaunchHost, project: string, now: number = Date.now()): Availability {
  if (host.state !== "connected") return { ok: false, reason: stateReason(host, now) };
  if (host.projects !== null && !host.projects.includes(project)) {
    return {
      ok: false,
      reason: `no path for ${project} on ${host.name}: hx hosts map ${project} ${host.name} <path>`,
    };
  }
  return { ok: true, reason: "" };
}

function byIndex(host: LaunchHost): GpuInfo[] {
  return [...host.gpus].sort((a, b) => a.index - b.index);
}

/** Indices of GPUs no hx run holds and no other process uses (spec 8A.5). SLURM: none. */
export function freeGpus(host: LaunchHost): number[] {
  if (host.kind === "slurm") return [];
  return byIndex(host)
    .filter((g) => !g.external && g.run_id == null)
    .map((g) => g.index);
}

/** One cell per GPU for the mini map in a host row. */
export function gpuCells(host: LaunchHost): GpuCell[] {
  return byIndex(host).map((g) => {
    if (host.state === "stale") return "stale";
    if (host.state !== "connected") return "none";
    if (g.external) return "other";
    return g.run_id == null ? "free" : "busy";
  });
}

/** Most GPUs one run may ask for: the host's GPU count, or `SLURM_MAX_GPUS` on SLURM. */
export function gpuLimit(host: LaunchHost): number {
  return host.kind === "slurm" ? SLURM_MAX_GPUS : host.gpus.length;
}

/**
 * GPUs per run after picking `host` (coming `from` the host picked before, if any): 0 on a
 * host without GPUs, else `prev` within 0..limit. A 0 that `from` forced (it had no GPUs)
 * goes back to 1; a chosen 0 (a CPU run, e.g. a CPU template) stays 0.
 */
export function gpusForHost(prev: number, host: LaunchHost, from: LaunchHost | null = null): number {
  const limit = gpuLimit(host);
  if (limit === 0) return 0;
  const forced = prev <= 0 && from !== null && gpuLimit(from) === 0;
  return Math.min(forced ? 1 : Math.max(prev, 0), limit);
}

/** Initial GPU request: an explicit template request wins, including CPU-only zero. */
export function initialGpus(host: LaunchHost, requested?: number): number {
  return requested ?? host.slurm?.defaults?.gpus ?? gpusForHost(1, host);
}

/** Resolve a template by verified environment identity, retaining unavailable hosts. */
export function initialHost(
  hosts: readonly LaunchHost[],
  project: string,
  preferred: string | null,
  environment?: string,
): string | null {
  if (environment !== undefined) {
    const matches = hosts.filter((host) => host.environment_id === environment);
    return matches.length === 1 ? matches[0]!.name : null;
  }
  return preferred ?? pickHost(hosts, project, null);
}

/** The preferred host when it can take the run, else the available host with most free GPUs. */
export function pickHost(
  hosts: readonly LaunchHost[],
  project: string,
  preferred: string | null,
  now: number = Date.now(),
): string | null {
  const ok = hosts.filter((h) => availability(h, project, now).ok);
  if (preferred !== null && ok.some((h) => h.name === preferred)) return preferred;
  let best: LaunchHost | null = null;
  for (const h of ok) {
    if (best === null || freeGpus(h).length > freeGpus(best).length) best = h;
  }
  return best === null ? null : best.name;
}

/**
 * How `n` seeds of `gpus` GPUs each land on `host` right now. SLURM queues every job itself.
 * Only SSH hosts run the hx queue; on the hub `queue` is ignored (it runs no scheduler).
 */
export function planLaunch(host: LaunchHost, gpus: number, n: number, queue: boolean): LaunchPlan {
  if (host.kind === "slurm") return { now: 0, queued: n, blocked: 0, cvd: [], firstPos: null };
  if (gpus <= 0) return { now: n, queued: 0, blocked: 0, cvd: [], firstPos: null };
  const free = freeGpus(host);
  const now = Math.min(n, Math.floor(free.length / gpus));
  const rest = n - now;
  const cvd = now > 0 ? free.slice(0, gpus) : [];
  if (host.kind === "ssh" && queue) {
    return { now, queued: rest, blocked: 0, cvd, firstPos: rest > 0 ? host.queue + 1 : null };
  }
  return { now, queued: 0, blocked: rest, cvd, firstPos: null };
}

/** `pos 4–5` for the waiting seeds; `""` when none waits in the hx queue. */
export function posRange(plan: LaunchPlan): string {
  if (plan.queued === 0 || plan.firstPos === null) return "";
  if (plan.queued === 1) return `pos ${plan.firstPos}`;
  return `pos ${plan.firstPos}–${plan.firstPos + plan.queued - 1}`;
}

/**
 * The footer line: `3 × 1 GPU on gpu1`, `3 jobs × 2 GPU, ≤ 08:00:00` (no `≤` part when the
 * time is left to the host's default), `3 runs on local, no GPU`.
 */
export function launchSummary(host: LaunchHost, gpus: number, n: number, time: string): string {
  if (host.kind === "slurm") {
    const t = time.trim();
    return `${n} ${n === 1 ? "job" : "jobs"} × ${gpus} GPU${t ? `, ≤ ${t}` : ""}`;
  }
  if (gpus === 0) return `${n} ${n === 1 ? "run" : "runs"} on ${host.name}, no GPU`;
  return `${n} × ${gpus} GPU on ${host.name}`;
}

/** Tooltip of a host row that can take the run. */
export function hostTitle(host: LaunchHost): string {
  if (host.kind === "slurm") {
    const s = host.slurm;
    return s ? `${host.name}: ${s.running} running, ${s.pending} pending in SLURM` : `${host.name}: SLURM`;
  }
  const names = [...new Set(host.gpus.map((g) => g.name))].join(", ");
  const kinds = names ? ` (${names})` : "";
  return `${host.name}: ${host.gpus.length} GPU${kinds}, ${freeGpus(host).length} free, ${host.queue} queued`;
}

/** Supported finite `sbatch --time` forms: `m`, `m:s`, `h:m:s`, `d-h`, `d-h:m`, `d-h:m:s`. */
export const SLURM_TIME = /^(\d+|\d+:\d{2}|\d+:\d{2}:\d{2}|\d+-\d+|\d+-\d+:\d{2}|\d+-\d+:\d{2}:\d{2})$/;

export function validSlurmTime(time: string): boolean {
  return SLURM_TIME.test(time.trim());
}

/**
 * The `slurm` launch field: only the fields the user filled in, plus GPUs per job.
 *
 * The backend merges it over the host's `SlurmDefaults` with `exclude_unset`, so every key
 * sent counts, even `null`: a blank field is left out to keep the host's partition, account
 * and time, and `extra` is never sent, so the host's extra `#SBATCH` lines stay.
 */
export function slurmBody(fields: SlurmFields, gpus: number): Partial<SlurmDefaults> {
  const body: Partial<SlurmDefaults> = {};
  const partition = fields.partition.trim();
  const account = fields.account.trim();
  const time = fields.time.trim();
  if (partition) body.partition = partition;
  if (account) body.account = account;
  if (time) body.time = time;
  body.gpus = gpus;
  return body;
}
