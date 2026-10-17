import "./baselines.css";
import type { BaselineRow } from "../../api/models";
import type { PanelResult } from "../../panels";
import type { DotCIReference } from "../../charts/DotCIChart";
export function baselineValue(row: BaselineRow, primary: string): number | null { const value = row.values[primary]; return typeof value === "number" && Number.isFinite(value) ? value : null; }
export function baselineSource(url: string): string | null { try { const value = new URL(url); return value.protocol === "https:" || value.protocol === "http:" ? value.href : null; } catch { return null; } }
export function baselineReferences(baselines: BaselineRow[], primary: string): DotCIReference[] {
  return baselines.flatMap((row) => { const value = baselineValue(row, primary); return value === null ? [] : [{ name: row.name, value, std: Number.isFinite(row.std[primary]) ? row.std[primary] : undefined, source: row.source }]; });
}
export function withBaselines<T extends PanelResult>(result: T, baselines: BaselineRow[]): T {
  if (result.type !== "leaderboard" || typeof result.meta?.primary !== "string" || !result.meta.primary.includes("/")) return result;
  return { ...result, meta: { ...result.meta, baselines } };
}
export function PaperBaselines({ baselines, primary, versions, best, secondary }: { baselines: BaselineRow[]; primary: string; versions: Record<string, string>; best?: number | null; secondary?: string | null }) {
  if (!baselines.length) return null;
  const metric = primary.split("/")[0];
  return <section aria-label="Paper baselines" className="paper-baselines"><h3>Paper baselines</h3><div style={{ overflowX: "auto" }}><table aria-label="Paper baselines"><thead><tr><th>Reference</th><th>{primary} (published)</th>{secondary ? <th>{secondary} (published)</th> : null}<th>Value − best</th><th>Source</th><th>Version</th></tr></thead><tbody>{baselines.map((row) => {
    const value = baselineValue(row, primary); const std = row.std[primary]; const source = baselineSource(row.source_url); const delta = value !== null && best != null && Number.isFinite(best) ? value - best : null;
    return <tr key={row.name}><td>◇ {row.name}</td><td>{value === null ? "—" : `${value}${Number.isFinite(std) ? ` ± ${std} published std` : ""}`}</td>{secondary ? <td>{baselineValue(row, secondary) ?? "—"}</td> : null}<td>{delta === null ? "—" : `${delta >= 0 ? "+" : ""}${Number(delta.toPrecision(8))}`}</td><td>{source ? <a href={source} rel="noopener noreferrer" target="_blank">{row.source}</a> : row.source}</td><td>{value !== null && row.version_match[metric] !== true ? <span title={`Published ${metric} value is not declared equivalent to our ${versions[metric] ?? "unknown"} version`}>≠{versions[metric] ?? "unknown"}</span> : "—"}</td></tr>;
  })}</tbody></table></div></section>;
}
export const BaselineRows = PaperBaselines;
