import type { CleanPlan, CleanPolicy, StorageItem } from "../../api/models";
export const validBytes = (n: number): boolean => Number.isSafeInteger(n) && n >= 0;
export function bytes(n: number): string {
  if (!validBytes(n)) return "Unknown bytes";
  const units = ["B", "kB", "MB", "GB", "TB", "PB"]; let index = 0; let size = n;
  while (size >= 1000 && index < units.length - 1) { size /= 1000; index++; }
  return `${index ? size.toFixed(1) : size} ${units[index]}`;
}
export function integer(value: string): number | null { if (!/^\d+$/.test(value)) return null; const n = Number(value); return validBytes(n) ? n : null; }
export function planLive(plan: CleanPlan, now: number): boolean { return validBytes(plan.total_bytes) && Number.isFinite(Date.parse(plan.expires_at)) && Date.parse(plan.expires_at) > now; }
export function confirmBytes(value: string, plan: CleanPlan, now: number): boolean { return planLive(plan, now) && integer(value) === plan.total_bytes; }
export function policy(days: string, kinds: string[], includePulled: boolean, project?: string): CleanPolicy | null {
  const age = integer(days); if (age === null || !kinds.length) return null;
  return { archived: true, older_than_days: age, kinds: [...kinds], include_pulled: includePulled, projects: project ? [project] : null, hosts: null };
}
export function largest(items: StorageItem[]): StorageItem[] { return [...items].sort((a, b) => b.bytes - a.bytes || `${a.environment_id}\0${a.path}\0${a.run_id}`.localeCompare(`${b.environment_id}\0${b.path}\0${b.run_id}`)); }
export function locality(item: StorageItem, hub: string | null | undefined): string { return !hub ? "Unknown locality" : item.environment_id === hub ? "Local" : "Remote"; }
export function ageLabel(mtime: number | null, now: number): string { return mtime === null || !Number.isFinite(mtime) || mtime * 1000 > now ? "—" : `${Math.floor((now - mtime * 1000) / 86400000)}d`; }

export function policyIdentity(value: CleanPolicy | null): string { return value ? JSON.stringify([value.archived, value.older_than_days, [...value.kinds].sort(), value.projects ?? null, value.hosts ?? null, value.include_pulled]) : "null"; }
