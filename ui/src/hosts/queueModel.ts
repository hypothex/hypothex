/** The Queue page's groups: queued runs by the host that serves their environment (spec 4.4). */
import type { HostRow, RunRecord } from "../api/models";
import { LOCAL_HOST, hostRowForRun } from "../pages/components/HostsPanel";
import { type QueueRow, queueRows } from "../pages/components/QueuePanel";

export interface QueueGroup {
  /** The environment id the group's runs share. */
  key: string;
  /** The hub's name for the host, else the machine's hostname from the first run. */
  host: string;
  /** The hosts row serving the environment; null while the list is unknown or none does. */
  row: HostRow | null;
  /** The group's queued runs in queue order, each with its record. */
  rows: (QueueRow & { record: RunRecord })[];
}

/**
 * Queued runs grouped by environment (one host serves one environment), each group in
 * queue order; the hub's own `local` group first, the rest by host name.
 */
export function queueGroups(runs: readonly RunRecord[], hosts: readonly HostRow[] | undefined, now: number): QueueGroup[] {
  const byEnv = new Map<string, RunRecord[]>();
  for (const r of runs) byEnv.set(r.environment_id, [...(byEnv.get(r.environment_id) ?? []), r]);
  const groups: QueueGroup[] = [];
  for (const [env, list] of byEnv) {
    const first = list[0];
    if (!first) continue;
    const row = hostRowForRun(first, hosts);
    const records = new Map(list.map((r) => [r.run_id, r]));
    const rows = queueRows(list, env, now).flatMap((q) => {
      const record = records.get(q.runId);
      return record ? [{ ...q, record }] : [];
    });
    if (rows.length === 0) continue;
    groups.push({ key: env, host: row?.name ?? first.host, row, rows });
  }
  return groups.sort((a, b) => Number(b.host === LOCAL_HOST) - Number(a.host === LOCAL_HOST) || a.host.localeCompare(b.host));
}
