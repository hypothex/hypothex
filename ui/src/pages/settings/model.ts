import type { DigestSettings, Principal, Scope, SessionRow, UserRow } from "../../api/models";
export const SCOPES: Scope[] = ["read", "launch", "admin"];
export const scopeGlyph = (scope: Scope): string => ({ read: "r", launch: "l", admin: "a" })[scope];
export const clientLabel = (client: string): string => ({ browser: "Browser", cli: "CLI", agent: "Agent", host: "Host", local: "Local" })[client] ?? client;
export function sessionState(session: SessionRow, now: number): "revoked" | "expired" | "active" | "unknown" {
  if (session.revoked_at) return "revoked";
  const expiry = Date.parse(session.expires_at);
  return Number.isFinite(expiry) ? expiry <= now ? "expired" : "active" : "unknown";
}
export function lastSeen(value: string, now: number): string {
  const time = Date.parse(value); if (!Number.isFinite(time) || time > now) return "—";
  const mins = Math.floor((now - time) / 60000);
  return mins < 1 ? "just now" : mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.floor(mins / 60)}h ago` : `${Math.floor(mins / 1440)}d ago`;
}
export function activeSessions(rows: SessionRow[], user: string, now: number): number { return rows.filter((r) => r.user === user && sessionState(r, now) === "active").length; }
export function validUser(name: string, users: UserRow[] = []): boolean { return /^[a-z][a-z0-9_-]{0,31}$/.test(name) && !users.some((u) => u.name === name); }
export function allowedScopes(issuer: Principal, user?: UserRow): Scope[] {
  if (user?.disabled_at || (issuer.scope !== "admin" && user && issuer.user !== user.name)) return [];
  const ceiling = Math.min(SCOPES.indexOf(issuer.scope), user ? SCOPES.indexOf(user.role) : 2);
  return SCOPES.filter((_, i) => i <= ceiling);
}
export const noticeGlyph = (state: string): string => ({ pending: "◷", sending: "↗", sent: "✓", failed: "✕", skipped: "−" })[state] ?? "?";

export const currentSession = (row: SessionRow, principal: Principal): boolean => row.id === principal.session_id;
export const eventGlyph = (event: string): string => ({ finished: "✓", failed: "✕", killed: "■", lost: "?" })[event] ?? "—";
export function digestSchedule(digest: DigestSettings): string { return digest.enabled ? `${digest.weekday} ${digest.hour}:00 · ${digest.timezone ?? "hub local timezone"}` : "Off"; }
