/** One cell per GPU, filled by utilisation (mockup .gpus); hx-run cells link to the run. */
import type { ReactElement } from "react";
import type { HostRow, RunRecord } from "../api/models";
import { fmtClock, isAgent } from "../pages/components/format";
import { type GpuCell, cellTitle } from "../pages/components/HostsPanel";
import { AppLink, hrefs } from "../pages/components/links";
import "./hosts.css";

export function GpuCells({ host, runs }: { host: HostRow; runs?: ReadonlyMap<string, RunRecord> }): ReactElement {
  if (host.slurm) return <span className="muted">{`${host.slurm.running} running · ${host.slurm.pending} pending`}</span>;
  if (host.gpus.length === 0) return <span className="muted">no GPU</span>;
  const stale = host.state.state === "stale";
  const asOf = stale ? fmtClock(host.state.since) : null;
  return (
    <span className={stale ? "gpus stale" : "gpus"} role="group" aria-label={`GPUs on ${host.name}`}>
      {[...host.gpus]
        .sort((a, b) => a.index - b.index)
        .map((g) => {
          const run = g.run_id ? runs?.get(g.run_id) : undefined;
          const cell: GpuCell = {
            kind: g.run_id ? (run ? (isAgent(run.created_by) ? "agent" : "human") : "run") : g.external ? "other" : "free",
            index: g.index,
            span: 1,
            runId: g.run_id,
            utils: [g.util],
            memUsedMb: g.mem_used_mb,
          };
          const cls = `gpu ${g.run_id ? "run" : g.external ? "ext" : "free"}`;
          const fill = <i style={{ height: `${Math.min(100, Math.max(0, g.util))}%` }} />;
          const title = cellTitle(host.name, cell, run, asOf);
          const name = title.split("\n")[0];
          return g.run_id ? (
            <AppLink key={g.index} data-gpu={g.index} className={cls} title={title} aria-label={name} href={hrefs.run(g.run_id)}>
              {fill}
            </AppLink>
          ) : (
            <span key={g.index} role="img" data-gpu={g.index} className={cls} title={title} aria-label={name}>
              {fill}
            </span>
          );
        })}
    </span>
  );
}
