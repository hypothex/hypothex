/**
 * Overview panel "Hosts" (spec 8A.7, 8A.8; mockup `docs/mockups/phase2/shot-overview-*`).
 *
 * One row per host: name and kind, connection state with the host's hx version (a `≠`
 * marks a version that differs from the hub's), one cell per GPU (agent run, human run,
 * free, not hx; a run on adjacent GPUs is one wide cell), SLURM running/pending counts,
 * queue length, $/GPU-h and cost today. A stale host keeps its last known cells, greyed.
 *
 * The pure helpers below (`gpuCells`, `hostTotals`, `hostsHeadline`, ...) are exported
 * for tests and for the Overview headline and metaline.
 */
import { useEffect, useState } from "react";
import { firstClause, isAgent, parseTime, shortId } from "./format";
import type { GpuInfo, HostRow, RunRecord } from "./types";

// formatting ---------------------------------------------------------------------------------

/** Dollars as in the mockup: whole dollars with commas from $10 (`$1,235`), else cents (`$0.50`). */
export function fmtMoney(usd: number): string {
  return usd >= 10 ? `$${Math.round(usd).toLocaleString("en-US")}` : `$${usd.toFixed(2)}`;
}

/** A short age: `59s`, `4m`, `2h`, `3d`; negative ages (clock skew) read `0s`. */
export function fmtAgeMs(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

const GPU_NOISE = /^(\d+GB|SXM\d*|PCIE|HBM\d*E?|NVL)$/i;

/** `NVIDIA A100-SXM4-80GB` → `A100`; `NVIDIA RTX A6000` → `RTX A6000`. */
export function shortGpuName(name: string): string {
  const parts = name
    .replace(/^(NVIDIA|Tesla)\s+/i, "")
    .split(/[-\s]+/)
    .filter((p) => p !== "" && !GPU_NOISE.test(p));
  return parts.length > 0 ? parts.join(" ") : name;
}

/** `5×A100 80GB` when every GPU is the same model and size, `3 GPUs` otherwise, `""` for none. */
export function gpuSpec(gpus: GpuInfo[]): string {
  if (gpus.length === 0) return "";
  const kinds = new Set(gpus.map((g) => `${shortGpuName(g.name)} ${Math.round(g.mem_total_mb / 1024)}GB`));
  const [only] = [...kinds];
  return kinds.size === 1 && only ? `${gpus.length}×${only}` : `${gpus.length} GPUs`;
}

// GPU cells ----------------------------------------------------------------------------------

/** What a GPU cell shows: an hx run by an agent, by a human, by an unknown launcher; free; not hx. */
export type CellKind = "agent" | "human" | "run" | "free" | "other";

export interface GpuCell {
  kind: CellKind;
  /** First GPU index the cell covers. */
  index: number;
  /** Adjacent GPUs covered (one hx run on several GPUs is one cell). */
  span: number;
  /** The hx run on these GPUs; null for free and not-hx cells. */
  runId: string | null;
  /** Utilisation in percent of each covered GPU, in index order. */
  utils: number[];
  /** Memory used on the covered GPUs, summed. */
  memUsedMb: number;
}

function cellKind(gpu: GpuInfo, runs: ReadonlyMap<string, RunRecord>): CellKind {
  const runId = gpu.run_id ?? null;
  if (runId === null) return gpu.external ? "other" : "free";
  const run = runs.get(runId);
  if (!run) return "run";
  return isAgent(run.created_by) ? "agent" : "human";
}

/**
 * The cells of one host, in GPU index order.
 *
 * A run on adjacent GPUs becomes one cell spanning them (mockup `6b0e 92% ×2`). An hx run
 * wins over `external` (the env server clears it on hx GPUs, but never trust that here).
 */
export function gpuCells(gpus: GpuInfo[], runs: ReadonlyMap<string, RunRecord>): GpuCell[] {
  const out: GpuCell[] = [];
  for (const gpu of [...gpus].sort((a, b) => a.index - b.index)) {
    const runId = gpu.run_id ?? null;
    const last = out[out.length - 1];
    if (runId !== null && last && last.runId === runId && last.index + last.span === gpu.index) {
      last.span += 1;
      last.utils.push(gpu.util);
      last.memUsedMb += gpu.mem_used_mb;
      continue;
    }
    out.push({
      kind: cellKind(gpu, runs),
      index: gpu.index,
      span: 1,
      runId,
      utils: [gpu.util],
      memUsedMb: gpu.mem_used_mb,
    });
  }
  return out;
}

/** Mean utilisation of a cell, rounded to a whole percent. */
export function meanUtil(cell: GpuCell): number {
  return Math.round(cell.utils.reduce((a, b) => a + b, 0) / cell.utils.length);
}

/** `GPU 3` or `GPU 0–1`. */
export function gpuRange(cell: GpuCell): string {
  return cell.span === 1 ? `GPU ${cell.index}` : `GPU ${cell.index}–${cell.index + cell.span - 1}`;
}

const gb = (mb: number): string => `${(mb / 1024).toFixed(1)} GB`;

/**
 * Tooltip of a cell, one fact per line: where, which run, its label and launcher,
 * per-GPU utilisation and memory, and `as of HH:MM` on a stale host.
 */
export function cellTitle(host: string, cell: GpuCell, run: RunRecord | undefined, asOf: string | null): string {
  const where = `${host} ${gpuRange(cell)}`;
  if (cell.kind === "free") return `${where}: free`;
  const usage = `${gb(cell.memUsedMb)}`;
  const lines =
    cell.kind === "other"
      ? [`${where}: not hx`, `${meanUtil(cell)}%, ${usage}`]
      : [
          `${where}: ${shortId(cell.runId ?? "")}`,
          ...(run ? [firstClause(run.hypothesis, `run ${shortId(run.run_id)}`), run.created_by] : []),
          `${cell.utils.map((u, k) => `GPU ${cell.index + k} ${Math.round(u)}%`).join(", ")}, ${usage}`,
        ];
  if (asOf !== null) lines.push(`as of ${asOf}`);
  return lines.join("\n");
}

/** GPU columns of the panel: 8, or more when a host has a higher GPU index. */
export function gpuColumns(hosts: HostRow[]): number {
  return Math.max(8, ...hosts.flatMap((h) => h.gpus.map((g) => g.index + 1)));
}

// hosts and runs -----------------------------------------------------------------------------

/** Name of the hub's own row in `GET /api/v1/hosts` (reserved in `environments.yaml`). */
export const LOCAL_HOST = "local";

/** Every row but the hub's own (`host_rows` always lists `local` first). */
export function remoteRows<R extends HostRow>(rows: readonly R[]): R[] {
  return rows.filter((r) => r.name !== LOCAL_HOST);
}

/**
 * The hosts row that serves a run: the row whose `state.environment_id` is the run's
 * `environment_id`, the match the backend's `host_for_environment` makes. Null when no row
 * does (the list is not loaded, or no host serves that environment). Never `executor.host`:
 * the backend writes the env server's own hostname there (`socket.gethostname()`), which is
 * not the hub's name for the host, and it sets it on hub runs too.
 */
export function hostRowForRun<R extends HostRow>(
  record: Pick<RunRecord, "environment_id">,
  hosts: readonly R[] | undefined,
): R | null {
  const env = record.environment_id;
  if (!env || hosts === undefined) return null;
  return hosts.find((h) => h.state.environment_id === env) ?? null;
}

/** Hours a host may stay unreachable before the Overview banner when the hub sends none. */
export const DEFAULT_STALE_BANNER_HOURS = 24;

/**
 * The banner threshold in hours: `stale_banner_hours` of the hosts list (the hub's
 * `environments.yaml` setting, the same on every row; controller ruling R1), else 24.
 */
export function staleBannerHours(hosts: readonly HostRow[]): number {
  const hours = hosts.find((h) => h.stale_banner_hours !== undefined)?.stale_banner_hours;
  return typeof hours === "number" && Number.isFinite(hours) && hours > 0 ? hours : DEFAULT_STALE_BANNER_HOURS;
}

/**
 * Hosts stale for more than `hours` at `now`, in host order, with how long (spec 5.6: a
 * banner, and the runs stay stale, never lost).
 */
export function longStale(
  hosts: readonly HostRow[],
  now: number,
  hours: number = DEFAULT_STALE_BANNER_HOURS,
): { name: string; age: string }[] {
  const limit = hours * 3_600_000;
  return hosts
    .filter((h) => h.state.state === "stale" && now - parseTime(h.state.since) > limit)
    .map((h) => ({ name: h.name, age: fmtAgeMs(now - parseTime(h.state.since)) }));
}

// totals, headline, metaline -----------------------------------------------------------------

export interface HostTotals {
  /** hx runs on host GPUs (distinct run ids) plus SLURM running jobs. */
  running: number;
  /** Host queue lengths plus SLURM pending jobs. */
  waiting: number;
  /** GPUs on connected hosts with no hx run and no other process. */
  freeGpus: number;
  /** Sum of `cost_today_usd`. */
  usdToday: number;
  /** Stale hosts with how long they have been stale (`4m`). */
  stale: { name: string; age: string }[];
}

/** Totals over all hosts at time `now` (ms since the epoch). */
export function hostTotals(hosts: HostRow[], now: number): HostTotals {
  const runIds = new Set<string>();
  let slurmRunning = 0;
  let waiting = 0;
  let freeGpus = 0;
  let usdToday = 0;
  const stale: HostTotals["stale"] = [];
  for (const h of hosts) {
    for (const g of h.gpus) {
      if (g.run_id) runIds.add(g.run_id);
      else if (!g.external && h.state.state === "connected") freeGpus += 1;
    }
    slurmRunning += h.slurm?.running ?? 0;
    waiting += h.queue + (h.slurm?.pending ?? 0);
    usdToday += h.cost_today_usd;
    if (h.state.state === "stale") stale.push({ name: h.name, age: fmtAgeMs(now - parseTime(h.state.since)) });
  }
  return { running: runIds.size + slurmRunning, waiting, freeGpus, usdToday, stale };
}

function count(counts: Record<string, number>, key: string): number | undefined {
  const v = (counts as Partial<Record<string, number>>)[key];
  return typeof v === "number" ? v : undefined;
}

/**
 * The Overview headline with hosts: `12 running, 11 waiting. dgx stale 4m`.
 *
 * Running and waiting come from the backend overview (`counts.running`,
 * `counts.queued`, which include mirrored remote runs); when a count is missing it is
 * computed from the hosts. Staleness is derived on the hub and never stored, so it always
 * comes from the hosts.
 */
export function hostsHeadline(counts: Record<string, number>, totals: HostTotals): string {
  const running = count(counts, "running") ?? totals.running;
  const waiting = count(counts, "queued") ?? totals.waiting;
  const parts = [running > 0 ? `${running} running` : "", waiting > 0 ? `${waiting} waiting` : ""];
  const said = parts.filter((p) => p !== "");
  const head = said.length > 0 ? `${said.join(", ")}.` : "Idle.";
  const stale = totals.stale.map((s) => `${s.name} stale ${s.age}`).join(", ");
  return stale ? `${head} ${stale}` : head;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** Metaline under the headline: `1 GPU free`, `$332 today`, `hub hx 0.5.0`, `4 hosts`. */
export function hostsMetaline(totals: HostTotals, hubVersion: string | null, nHosts: number): string[] {
  return [
    `${plural(totals.freeGpus, "GPU", "GPUs")} free`,
    `${fmtMoney(totals.usdToday)} today`,
    ...(hubVersion ? [`hub hx ${hubVersion}`] : []),
    plural(nHosts, "host", "hosts"),
  ];
}

/** The current time, refreshed every `intervalMs` (stale ages tick without a refetch). */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
