import { useState } from "react";
import type { StorageItem } from "../../api/models";
import { PanelSection } from "../../chrome/PanelSection";
import { AppLink, hrefs } from "../components/links";
import { ageLabel, bytes, largest, locality } from "./model";
export function LargestItems({ items, hub }: { items: StorageItem[]; hub?: string | null }) {
  const [limit, setLimit] = useState(20); const sorted = largest(items);
  return <PanelSection title="Largest" grid="wide"><div className="phase3-section"><div className="phase3-scroll"><table aria-label="Largest storage items"><thead><tr>{["Run", "Host / environment", "Kind", "Path", "Bytes", "Age", "State"].map((title) => <th key={title}>{title}</th>)}</tr></thead><tbody>{sorted.slice(0, limit).map((item, i) => <tr key={`${item.environment_id}:${item.path}:${item.run_id}:${i}`}><td><AppLink href={hrefs.run(item.run_id)}>{item.run_id}</AppLink></td><td>{item.host}<br />{item.environment_id} · {locality(item, hub)}</td><td>{item.artifact_kind ?? item.kind}</td><td className="storage-path" title={item.path}>{item.path}</td><td title={`${item.bytes} bytes`}>{bytes(item.bytes)}</td><td>{ageLabel(item.mtime, Date.now())}</td><td>{[item.archived ? "Archived" : "Not archived", item.starred ? "Starred" : "Unstarred", item.exists ? "Exists" : "Missing"].join(" · ")}</td></tr>)}</tbody></table></div>{!items.length ? <p>No storage items</p> : null}{limit < items.length ? <button className="btn" onClick={() => setLimit((n) => n + 20)}>Show more ({items.length - limit})</button> : null}</div></PanelSection>;
}
