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
import { type CSSProperties, createElement, useEffect, useState } from "react";
import { firstClause, fmtClock, isAgent, parseTime, shortId } from "./format";
import { AppLink, hrefs } from "./links";
import type { ConnState, GpuInfo, HostRow, RunRecord } from "./types";

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

/**
 * `count` GPUs named after `gpus`: `2×A100 80GB` when every one of `gpus` is the same model
 * and size, else `1 GPU`, `2 GPUs`. The one GPU text of the hosts grid and the run page.
 */
export function gpuCountLabel(count: number, gpus: readonly GpuInfo[]): string {
  const kinds = new Set(gpus.map((g) => `${shortGpuName(g.name)} ${Math.round(g.mem_total_mb / 1024)}GB`));
  const [only] = [...kinds];
  if (kinds.size === 1 && only) return `${count}×${only}`;
  return `${count} ${count === 1 ? "GPU" : "GPUs"}`;
}

/** `5×A100 80GB` when every GPU is the same model and size, `3 GPUs` otherwise, `""` for none. */
export function gpuSpec(gpus: GpuInfo[]): string {
  return gpus.length === 0 ? "" : gpuCountLabel(gpus.length, gpus);
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

// component ----------------------------------------------------------------------------------

/** Panel CSS, scoped under `.page .hosts`, `.page .hosts-key` and `.page .hosts-banner` (values from the mockup). */
export const HOSTS_CSS = `
.page .hosts { font-variant-numeric: tabular-nums; }
.page .hosts .hrow { display: grid; grid-template-columns: 168px 132px minmax(0, 1fr) 52px 70px 70px; gap: 0 18px; align-items: center; padding: 14px 0; border-top: 1px solid var(--rule-2); }
.page .hosts .hrow.head { padding: 0 0 8px; border-top: 0; border-bottom: 1px solid var(--rule); font-size: 12.5px; color: var(--ink-3); align-items: end; }
.page .hosts .hrow.head + .hrow { border-top: 0; }
.page .hosts .r { text-align: right; }
.page .hosts .hn b { font-weight: 600; font-size: 15px; margin-right: 8px; }
.page .hosts .kind { font-size: 11.5px; color: var(--ink-2); border: 1px solid var(--rule); border-radius: 9px; padding: 0 7px; }
.page .hosts .meta { font-size: 12.5px; color: var(--ink-3); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.page .hosts .hs { font-size: 13.5px; color: var(--ink-2); }
.page .hosts .hs .st { font-weight: 400; color: var(--ink-2); gap: 7px; }
.page .hosts .hs b { color: var(--ink); font-weight: 600; }
.page .hosts .q { font-size: 15px; }
.page .hosts .money { font-size: 14px; }
.page .hosts .z { color: var(--ink-3); }
.page .hosts .ver { display: inline-flex; gap: 5px; align-items: center; cursor: help; }
.page .hosts .ver .ne { color: var(--fail); font-weight: 650; }
.page .hosts .ver.bad { color: var(--ink); }
.page .hosts .cells, .page .hosts .gidx { display: grid; gap: 4px; }
.page .hosts .gidx span { font-size: 11.5px; color: var(--ink-3); padding-left: 2px; }
.page .hosts .gc { position: relative; height: 44px; border-radius: 4px; padding: 5px 7px 0 9px; font-size: 13px; line-height: 1.25; overflow: hidden; white-space: nowrap; text-decoration: none; color: var(--ink); }
.page .hosts .gc .id { font-weight: 550; }
.page .hosts .gc .u { display: block; font-size: 12px; color: var(--ink-3); }
.page .hosts .gc.busy { background: var(--paper-2); }
.page .hosts .gc.busy::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--ink-3); }
.page .hosts .gc.agent::before { background: var(--agent); }
.page .hosts .gc.human::before { background: var(--human); }
.page .hosts .gc .ub { position: absolute; left: 9px; right: 7px; bottom: 6px; height: 2px; background: var(--rule); border-radius: 1px; }
.page .hosts .gc .ub i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--ink-2); border-radius: 1px; }
.page .hosts .gc.free { border: 1px dashed var(--rule); color: var(--ink-3); padding-left: 8px; }
.page .hosts .gc.other { border: 1px solid var(--rule); color: var(--ink-2); padding-left: 8px; background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--ink-3) 22%, transparent) 0 1px, transparent 1px 6px); }
.page .hosts .gc.other .id { font-weight: 450; }
.page .hosts .hrow.stale .cells { opacity: .42; filter: grayscale(1); }
.page .hosts .hrow.stale .hn b { color: var(--ink-2); }
.page .hosts .msg { font-size: 13px; color: var(--ink-2); }
.page .hosts .slurm { display: flex; align-items: baseline; }
.page .hosts .slurm > div { padding: 0 22px; border-left: 1px solid var(--rule-2); cursor: help; }
.page .hosts .slurm > div:first-child { padding-left: 2px; border-left: 0; }
.page .hosts .slurm b { font: 400 21px/1 var(--sans); letter-spacing: -.01em; color: var(--ink); margin-right: 6px; }
.page .hosts .slurm span { font-size: 12.5px; color: var(--ink-3); }
.page .hosts-key .gk { display: inline-block; width: 18px; height: 12px; border-radius: 2px; }
.page .hosts-key .gk.agent { background: var(--paper-2); box-shadow: inset 3px 0 0 var(--agent); }
.page .hosts-key .gk.human { background: var(--paper-2); box-shadow: inset 3px 0 0 var(--human); }
.page .hosts-key .gk.free { border: 1px dashed var(--ink-3); }
.page .hosts-key .gk.other { border: 1px solid var(--rule); background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--ink-3) 40%, transparent) 0 1px, transparent 1px 4px); }
.page .hosts-key .ne { color: var(--fail); font-weight: 650; }
.page .hosts-banner { margin: 12px 0 0; padding: 10px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 14px; color: var(--ink-2); }
.page .hosts-banner b { color: var(--ink); font-weight: 600; }
`;

/**
 * One glyph per state, never colour alone (mockup `GL`).
 *
 * connected: filled dot; stale: half-filled ring; connecting: open arc;
 * bootstrapping: dashed ring; upgrade: up arrow; error: red cross;
 * disabled: plain ring.
 */
export function StateGlyph({ state }: { state: ConnState }) {
  const ring = (dash?: string) => (
    <circle cx="5" cy="5" r="4" style={{ fill: "none", stroke: "var(--ink-2)", strokeWidth: 1.4, strokeDasharray: dash }} />
  );
  let body;
  if (state === "connected") body = <circle cx="5" cy="5" r="4" style={{ fill: "var(--ink-2)" }} />;
  else if (state === "stale")
    body = (
      <>
        <circle cx="5" cy="5" r="4" style={{ fill: "none", stroke: "var(--ink)", strokeWidth: 1.4 }} />
        <path d="M5 1a4 4 0 0 1 0 8z" style={{ fill: "var(--ink)" }} />
      </>
    );
  else if (state === "connecting")
    // Open three-quarter arc: a ring not yet closed.
    body = <path d="M5 1a4 4 0 1 1 -4 4" style={{ fill: "none", stroke: "var(--ink-2)", strokeWidth: 1.4 }} />;
  else if (state === "bootstrapping") body = ring("1.6 1.6");
  else if (state === "upgrade")
    body = <path d="M5 9V1.6M1.8 4.6L5 1.4L8.2 4.6" style={{ fill: "none", stroke: "var(--ink-2)", strokeWidth: 1.4 }} />;
  else if (state === "error")
    body = <path d="M1.4 1.4L8.6 8.6M8.6 1.4L1.4 8.6" style={{ stroke: "var(--fail)", strokeWidth: 1.4 }} />;
  else body = ring();
  return (
    <svg width="10" height="10" aria-hidden="true" data-state={state}>
      {body}
    </svg>
  );
}

function Version({ host, version, hub }: { host: string; version: string | null; hub: string | null }) {
  if (!version) return <span>hx ·</span>;
  const bad = hub !== null && version !== hub;
  return (
    <span
      className={bad ? "ver bad" : "ver"}
      title={bad ? `hub runs hx ${hub}. Update: hx hosts upgrade ${host}` : `hx ${version}`}
    >
      {`hx ${version}`}
      {bad ? <span className="ne">≠</span> : null}
    </span>
  );
}

function stateTitle(row: HostRow): string {
  const st = row.state;
  if (st.state === "stale") return `No heartbeat since ${fmtClock(st.since)}. Cells show the last known state.`;
  if (st.state === "upgrade") return st.message || `hx hosts upgrade ${row.name}`;
  return st.message || `${st.state} since ${fmtClock(st.since)}`;
}

function StateCell({ row, hub, now }: { row: HostRow; hub: string | null; now: number }) {
  const st = row.state;
  const stale = st.state === "stale";
  const word = stale ? `stale ${fmtAgeMs(now - parseTime(st.since))}` : st.state;
  return (
    <div className="hs">
      <span className="st" title={stateTitle(row)}>
        <StateGlyph state={st.state} />
        {stale ? <b>{word}</b> : word}
      </span>
      <div className="meta">
        <Version host={row.name} version={st.hx_version ?? null} hub={hub} />
        {stale ? `  as of ${fmtClock(st.since)}` : null}
      </div>
    </div>
  );
}

interface CellProps {
  host: string;
  cell: GpuCell;
  run: RunRecord | undefined;
  asOf: string | null;
}

function Cell({ host, cell, run, asOf }: CellProps) {
  const style: CSSProperties = { gridColumn: `${cell.index + 1} / span ${cell.span}` };
  const title = cellTitle(host, cell, run, asOf);
  if (cell.kind === "free") {
    return (
      <div className="gc free" style={style} title={title}>
        free
      </div>
    );
  }
  const util = meanUtil(cell);
  if (cell.kind === "other") {
    return (
      <div className="gc other" style={style} title={title}>
        <span className="id">not hx</span>
        <span className="u">{`${util}%`}</span>
      </div>
    );
  }
  const runId = cell.runId ?? "";
  return (
    <AppLink className={`gc busy ${cell.kind}`} style={style} title={title} href={hrefs.run(runId)}>
      <span className="id">{shortId(runId)}</span>
      <span className="u">{cell.span > 1 ? `${util}% ×${cell.span}` : `${util}%`}</span>
      <span className="ub">
        <i style={{ width: `${Math.min(100, Math.max(0, util))}%` }} />
      </span>
    </AppLink>
  );
}

function Cells({ row, runs, columns }: { row: HostRow; runs: ReadonlyMap<string, RunRecord>; columns: number }) {
  if (row.slurm) {
    return (
      <div className="slurm">
        <div title={`hx jobs running on ${row.name}`}>
          <b>{row.slurm.running}</b>
          <span>running</span>
        </div>
        <div title={`hx jobs pending on ${row.name}`}>
          <b>{row.slurm.pending}</b>
          <span>pending</span>
        </div>
      </div>
    );
  }
  if (row.gpus.length === 0) {
    const text = row.state.state === "connected" ? (row.kind === "slurm" ? "·" : "no GPUs") : row.state.message || "·";
    return <div className="msg">{text}</div>;
  }
  const asOf = row.state.state === "stale" ? fmtClock(row.state.since) : null;
  return (
    <div className="cells" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
      {gpuCells(row.gpus, runs).map((cell) => (
        <Cell
          key={cell.index}
          host={row.name}
          cell={cell}
          run={cell.runId ? runs.get(cell.runId) : undefined}
          asOf={asOf}
        />
      ))}
    </div>
  );
}

function HostLine(props: { row: HostRow; runs: ReadonlyMap<string, RunRecord>; hub: string | null; now: number; columns: number }) {
  const { row, runs, hub, now, columns } = props;
  const rate = row.usd_per_gpu_hour ?? null;
  const cost = row.cost_today_usd;
  return (
    <div className={row.state.state === "stale" ? "hrow stale" : "hrow"} role="group" aria-label={row.name}>
      <div className="hn">
        <div>
          <b>{row.name}</b>
          <span className="kind">{row.name === "local" ? "hub" : row.kind}</span>
        </div>
        <div className="meta" title={row.projects.join(", ")}>
          {gpuSpec(row.gpus) || "·"}
        </div>
      </div>
      <StateCell row={row} hub={hub} now={now} />
      <Cells row={row} runs={runs} columns={columns} />
      <div className={row.queue > 0 ? "r q" : "r q z"} title={row.queue > 0 ? `${row.queue} hx runs waiting for GPUs` : "Queue empty"}>
        {row.queue}
      </div>
      <div className={rate !== null ? "r money" : "r money z"} title={rate !== null ? "$/GPU-h from environments.yaml" : "No rate set"}>
        {rate !== null ? `$${rate.toFixed(2)}` : "·"}
      </div>
      <div className={cost > 0 ? "r money" : "r money z"} title="GPU and API cost of runs today">
        {cost > 0 ? fmtMoney(cost) : "·"}
      </div>
    </div>
  );
}

export interface HostsPanelProps {
  /** `GET /api/v1/hosts`. */
  hosts: HostRow[];
  /** Active runs (`OverviewSummary.running`), for each cell's launcher and label. */
  runs: RunRecord[];
  /** hx version of the hub; null while unknown (then no `≠` marks). */
  hubVersion: string | null;
  /** Current time in ms, for stale ages. */
  now: number;
}

/** The Hosts panel body: header, one row per host, and the key. */
export function HostsPanel({ hosts, runs, hubVersion, now }: HostsPanelProps) {
  if (hosts.length === 0) return <p className="small">none</p>;
  const byId = new Map(runs.map((r) => [r.run_id, r]));
  const columns = gpuColumns(hosts);
  return (
    <>
      {createElement("style", { "data-hx": "hosts" }, HOSTS_CSS)}
      <div className="hosts">
        <div className="hrow head">
          <div>host</div>
          <div>state</div>
          <div className="gidx" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
            {Array.from({ length: columns }, (_, i) => (
              <span key={i}>{i}</span>
            ))}
          </div>
          <div className="r">queue</div>
          <div className="r">$/GPU‑h</div>
          <div className="r">today</div>
        </div>
        {hosts.map((row) => (
          <HostLine key={row.name} row={row} runs={byId} hub={hubVersion} now={now} columns={columns} />
        ))}
      </div>
      <div className="key hosts-key" aria-label="Key">
        <span><span className="gk agent" />agent run</span>
        <span><span className="gk human" />human run</span>
        <span><span className="gk free" />free</span>
        <span><span className="gk other" />not hx</span>
        <span><StateGlyph state="stale" />stale</span>
        <span><span>hx<span className="ne">≠</span></span>version mismatch</span>
      </div>
    </>
  );
}
