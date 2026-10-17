import type { StorageReport } from "../../api/models";
import { PanelSection } from "../../chrome/PanelSection";
import { bytes, locality } from "./model";
export function StorageBars({ report, hub }: { report: StorageReport; hub?: string | null }) {
  return <>{(["project", "host"] as const).map((dimension) => {
    const totals = dimension === "project" ? report.by_project : report.by_host;
    const max = Math.max(0, ...Object.values(totals));
    return <PanelSection key={dimension} title={`By ${dimension}`} grid="wide"><div className="phase3-section">{!Object.keys(totals).length ? <p>No storage measured</p> : Object.entries(totals).map(([key, total]) => {
      const rows = report.items.filter((item) => item[dimension] === key);
      const identities = [...new Set(rows.map((item) => `${item.host} · ${item.environment_id} · ${locality(item, hub)}`))];
      return <div className="storage-bar" key={key}><span>{key}</span><strong>{bytes(total)}</strong><meter min={0} max={max || 1} value={Math.max(0, total)} aria-label={`${key}: ${total} bytes`} /><small>{identities.join("; ")}</small></div>;
    })}{report.errors.length ? <p>Partial report; unreachable storage is unknown.</p> : null}</div></PanelSection>;
  })}</>;
}
