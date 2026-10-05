/**
 * Panel c (mockup "Runs on hosts"): the sweep's unfinished runs with params, seed, state
 * (`stale 4m`, `queued, pos 2`, `failed, exit 1`), host, GPU-hours and cost. Finished
 * runs collapse into one `+ N finished` row.
 */
import { type ReactElement, useState } from "react";
import type { HostRow, RunRecord } from "../../api/models";
import { billedGpus } from "./billedGpus";
import { DASH, fmtUsd, runSeconds } from "./format";
import { SweepRunLink } from "./SweepGlyphs";
import { type RunGlyphState, gpuHours, hostOf, runState, runUsd, stateText } from "./SweepModel";

export interface SweepRunsProps {
  /** The sweep's runs, in launch order. */
  runs: readonly RunRecord[];
  /** Param columns, in grid order. */
  names: readonly string[];
  /** `staleHosts(hosts)`: environment id → since, for hosts that are not connected. */
  stale: ReadonlyMap<string, string>;
  /** `GET /api/v1/hosts`, to name each run's host; undefined while it loads or fails. */
  hosts: readonly HostRow[] | undefined;
  now: number;
}

const RANK: Record<RunGlyphState, number> = {
  running: 0,
  stale: 0,
  queued: 1,
  failed: 2,
  lost: 2,
  killed: 3,
  finished: 4,
};

/** Runs with their shown state: running and stale, queued by position, failed, killed, finished. */
export function runsForHosts(
  runs: readonly RunRecord[],
  stale: ReadonlyMap<string, string>,
): { record: RunRecord; state: RunGlyphState }[] {
  const pos = (r: RunRecord): number => r.executor.queue_position ?? Number.MAX_SAFE_INTEGER;
  return runs
    .map((record, i) => ({ record, state: runState(record, null, stale), i }))
    .sort((a, b) => RANK[a.state] - RANK[b.state] || pos(a.record) - pos(b.record) || a.i - b.i)
    .map(({ record, state }) => ({ record, state }));
}

export function SweepRuns({ runs, names, stale, hosts, now }: SweepRunsProps): ReactElement {
  const [showDone, setShowDone] = useState(false);
  if (runs.length === 0) return <p className="small">No runs indexed yet</p>;
  const rows = runsForHosts(runs, stale);
  const done = rows.filter((x) => x.state === "finished").length;
  const shown = showDone ? rows : rows.filter((x) => x.state !== "finished");
  return (
    <>
      <table className="sw-runs">
        <thead>
          <tr>
            <th>run</th>
            {names.map((n) => (
              <th key={n}>{n}</th>
            ))}
            <th className="r">seed</th>
            <th>state</th>
            <th>host</th>
            <th className="r" title="GPU-hours: wall time × GPUs">
              GPU-h
            </th>
            <th className="r">cost</th>
          </tr>
        </thead>
        <tbody>
          {shown.map(({ record, state }) => {
            const hours = gpuHours(record, now);
            const usd = runUsd(record);
            const terminal = record.status !== "running" && record.status !== "queued";
            const timed = runSeconds(record, now) !== null && (!terminal || record.ended_at !== null);
            const knownHours = record.cost != null || (record.status !== "queued" && (billedGpus(record) === 0 || timed));
            return (
              <tr key={record.run_id}>
                <td>
                  <SweepRunLink runId={record.run_id} state={state} title={record.run_id} />
                </td>
                {names.map((n) => (
                  <td key={n}>{record.params[n] ?? DASH}</td>
                ))}
                <td className="r">{record.seed ?? DASH}</td>
                <td>{stateText(record, state, stale, now)}</td>
                <td>{hostOf(record, hosts)}</td>
                <td className="r">{knownHours ? hours.toFixed(1) : terminal ? DASH : "·"}</td>
                <td className="r">{usd !== null ? fmtUsd(usd) : terminal ? DASH : "·"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {done > 0 ? (
        <button
          type="button"
          className="btn link more-runs"
          aria-expanded={showDone}
          onClick={() => setShowDone((v) => !v)}
        >
          {showDone ? "hide finished" : `+ ${done} finished`}
        </button>
      ) : null}
    </>
  );
}
