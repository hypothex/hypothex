/** Helpers for the specs that run against the `hx demo --with-hosts` hub (fake hosts). */
import type { APIRequestContext } from "@playwright/test";
import { expect, getJson } from "./fixtures";

export interface GpuLite {
  index: number;
  run_id: string | null;
  external: boolean;
}
export interface HostLite {
  name: string;
  kind: "local" | "ssh" | "slurm";
  state: { state: string; environment_id: string | null };
  gpus: GpuLite[];
  queue: number;
  projects: string[];
}
export interface ExecutorLite {
  host?: string | null;
  gpus?: number[];
  slurm_job_id?: string | null;
  queue_position?: number | null;
}
export interface RecordLite {
  run_id: string;
  project: string;
  environment_id: string;
  hypothesis: string;
  status: string;
  /** `executor.host` is the env server's own hostname, not the hub's name for the host. */
  executor: ExecutorLite;
}
export interface TaskLite {
  name: string;
}
export interface SweepItemLite {
  id: string;
  n_runs: number;
}
export interface SweepLite {
  headline: string;
  /** The sweep's runs, derived by the hub from the runs tagged `tag` (not in the spec). */
  run_ids: string[];
  spec: { id: string; project: string };
}

/** `/api/v1/hosts` once every host is connected (the hub connects to them at start). */
export async function connectedHosts(request: APIRequestContext): Promise<HostLite[]> {
  let hosts: HostLite[] = [];
  await expect
    .poll(
      async () => {
        const response = await request.get("/api/v1/hosts");
        if (!response.ok()) return false;
        hosts = (await response.json()) as HostLite[];
        return hosts.length > 1 && hosts.every((h) => h.state.state === "connected");
      },
      { timeout: 60_000, message: "the demo hosts never all connected" },
    )
    .toBe(true);
  return hosts;
}

/** The fake remote hosts: every row except the hub itself (`local`). */
export function remoteHosts(hosts: HostLite[]): HostLite[] {
  return hosts.filter((h) => h.name !== "local");
}

/**
 * The host a run is on, matched by `environment_id` as the UI matches it (`hostRowForRun`).
 * Never `executor.host`: on a real host it is the machine's hostname (the demo happens to
 * use the host name as its label, so a spec reading it would pass here and fail for real).
 */
export function hostOfRun(hosts: HostLite[], run: RecordLite): HostLite | undefined {
  return hosts.find((h) => h.state.environment_id !== null && h.state.environment_id === run.environment_id);
}

/**
 * A run that holds GPUs on a fake host, and that host, once the hub mirrors one. The demo
 * posts its live runs to gpu1 as queued (`queue: true`); gpu1's scheduler starts the
 * running cells a few seconds later and the hub mirrors them after that, so a spec that
 * reads `/api/v1/runs` once, right after the hosts connect, can see none yet. Until this
 * resolves, a queued run may still be one of the cells that is about to start.
 */
export async function runningRemoteRun(
  request: APIRequestContext,
  hosts: HostLite[],
): Promise<{ run: RecordLite; host: HostLite }> {
  const found: { run?: RecordLite; host?: HostLite } = {};
  await expect
    .poll(
      async () => {
        const response = await request.get("/api/v1/runs?status=running&limit=500");
        if (!response.ok()) return false;
        const running = (await response.json()) as RecordLite[];
        found.run = running.find((r) => (r.executor.gpus ?? []).length > 0 && hostOfRun(hosts, r));
        found.host = found.run ? hostOfRun(hosts, found.run) : undefined;
        return found.host !== undefined;
      },
      { timeout: 60_000, message: "hx demo --with-hosts has no running run holding GPUs" },
    )
    .toBe(true);
  const { run, host } = found;
  if (!run || !host) throw new Error("hx demo --with-hosts has no running run holding GPUs");
  return { run, host };
}

/** The first sweep of the first project that has one. */
export async function firstSweep(request: APIRequestContext): Promise<{ project: string; id: string }> {
  const projects = await getJson<{ project: string }[]>(request, "/api/v1/projects");
  for (const { project } of projects) {
    const sweeps = await getJson<SweepItemLite[]>(
      request,
      `/api/v1/projects/${encodeURIComponent(project)}/sweeps`,
    );
    const first = sweeps[0];
    if (first) return { project, id: first.id };
  }
  throw new Error("hx demo --with-hosts seeded no sweep");
}
