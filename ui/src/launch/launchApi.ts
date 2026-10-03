/**
 * HTTP calls of the Launch dialog, through the shared client (`api.*`). The hub launches
 * with `POST /api/v1/runs`; every other host with `POST /api/v1/hosts/{host}/runs`
 * (contract section 2), which the hub forwards with the same `command_id`. One launch is
 * one POST per seed, in seed order (so queue positions follow seed order), each with
 * `command_id = <base>.s<seed>`.
 */
import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  GpuInfo,
  HostLaunchRequest,
  HostRow,
  LaunchRequest,
  QueueEntry,
  RunFields,
  RunRecord,
} from "../api/models";
import { HOSTS_REFETCH_MS, fetchHosts, queryKeys } from "../api/queries";
import { ACTION_RETRY_DELAY_MS, shouldRetry } from "../pages/components/useAction";
import { type LaunchHost, type LaunchSpec, slurmBody, toLaunchHosts } from "./plan";

/**
 * Hosts for the picker: the hub (with its GPUs and queue) first, then `GET /api/v1/hosts`.
 *
 * With `qc`, the hosts list is fetched through the shared `["hosts"]` query (`fetchHosts`),
 * so a stale host keeps the GPUs and queue it had while connected (`keepLastKnown`), as on
 * the Overview; the hub itself sends none for a host that is not connected.
 */
export async function fetchLaunchHosts(signal?: AbortSignal, qc?: QueryClient): Promise<LaunchHost[]> {
  const rows: Promise<HostRow[]> = qc
    ? qc.fetchQuery({
        queryKey: queryKeys.hosts(),
        queryFn: ({ signal: s }) => fetchHosts(qc, s),
        staleTime: 0,
      })
    : api.hosts(signal);
  const [hostRows, gpus, queue] = await Promise.all([
    rows,
    api.gpus(signal).catch((): GpuInfo[] => []),
    api.queue(signal).catch((): QueueEntry[] => []),
  ]);
  return toLaunchHosts(hostRows, { gpus, queue: queue.length });
}

/** Under `["hosts"]`, which `host.*` events and launches invalidate. */
export const LAUNCH_HOSTS_KEY = ["hosts", "launch"] as const;

/** Polls at the hosts list's rate: GPU use changes every 10 s with no event (spec 8A.7). */
export function useLaunchHosts() {
  const qc = useQueryClient();
  return useQuery({
    queryKey: LAUNCH_HOSTS_KEY,
    queryFn: ({ signal }) => fetchLaunchHosts(signal, qc),
    refetchInterval: HOSTS_REFETCH_MS,
  });
}

/**
 * The launch body for one seed, without the action fields (`api.*` adds `command_id` and
 * `created_by`): the phase 1 launch fields plus `gpus`, `queue`, on SLURM `slurm`, and the
 * pinned `commit` when there is one.
 *
 * The hub's own launch (`POST /api/v1/runs`) takes `repo`, the hub's checkout. A host launch
 * takes `project` by name and no path: `TaskDetail.repo` of a project copied from a host is
 * a path on that host, and the hub resolves its own checkout and the host's mapped one. No
 * `diff` is ever sent: without `commit` the hub pins its checkout's HEAD and diff itself.
 */
export function launchRequest(spec: LaunchSpec, seed: number): LaunchRequest | HostLaunchRequest {
  const fields: RunFields = {
    task: spec.task,
    command: spec.argv,
    hypothesis: spec.hypothesis.trim(),
    seed,
    tags: [],
    params: spec.params,
    vars: spec.vars,
    gpus: spec.gpus,
    queue: spec.host.kind === "ssh" && spec.queue,
  };
  if (spec.host.kind === "slurm" && spec.slurm !== null) fields.slurm = slurmBody(spec.slurm, spec.gpus);
  if (spec.commit !== null) fields.commit = spec.commit;
  return spec.host.kind === "hub" ? { repo: spec.repo, ...fields } : { project: spec.project, ...fields };
}

/** The idempotency key of one seed of one launch attempt. */
export const seedCommandId = (base: string, seed: number): string => `${base}.s${seed}`;

/** Launch one seed on the spec's host. */
export function postLaunch(spec: LaunchSpec, seed: number, commandId: string): Promise<RunRecord> {
  const body = launchRequest(spec, seed);
  const opts = { command_id: commandId };
  return "repo" in body ? api.launch(body, opts) : api.launchOnHost(spec.host.name, body, opts);
}

export interface LaunchOutcome {
  /** Runs started (or already started under the same `command_id`), in seed order. */
  records: RunRecord[];
  /** The first seed the server refused or never answered; later seeds were not sent. */
  failed: { seed: number; error: Error } | null;
}

export interface LaunchSeedsOptions {
  onProgress?: (done: number) => void;
  /** Wait before retrying an unanswered request; default `ACTION_RETRY_DELAY_MS`. */
  delayMs?: number;
}

/**
 * Launch every seed in order. An unanswered request (the server may not have seen it) is
 * retried twice with the same `command_id`; any answered failure stops the launch.
 */
export async function launchSeeds(
  spec: LaunchSpec,
  seeds: readonly number[],
  base: string,
  opts: LaunchSeedsOptions = {},
): Promise<LaunchOutcome> {
  const delay = opts.delayMs ?? ACTION_RETRY_DELAY_MS;
  const records: RunRecord[] = [];
  for (const seed of seeds) {
    const commandId = seedCommandId(base, seed);
    for (let attempt = 0; ; attempt += 1) {
      try {
        records.push(await postLaunch(spec, seed, commandId));
        break;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        if (!shouldRetry(attempt, error)) return { records, failed: { seed, error } };
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
    opts.onProgress?.(records.length);
  }
  return { records, failed: null };
}
