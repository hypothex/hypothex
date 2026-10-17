import { describe, expect, test } from "bun:test";
import type { Principal, Scope, SessionRow, UserRow } from "../../src/api/models";
import { activeSessions, allowedScopes, clientLabel, currentSession, digestSchedule, eventGlyph, scopeGlyph, lastSeen, noticeGlyph, sessionState, validUser } from "../../src/pages/settings/model";
const now = Date.parse("2026-10-17T10:00:00Z");
const principal: Principal = { auth: "on", user: "alice", scope: "admin", scopes: ["read", "launch", "admin"], client: "browser", session_id: "s_one", public_url: null };
const user: UserRow = { name: "alice", role: "launch", created_at: "2026-01-01", created_by: "local", disabled_at: null };
const session: SessionRow = { id: "s_one", user: "alice", client: "browser", scope: "launch", device: "Test", created_at: "2026-01-01", last_seen_at: "2026-10-17T09:59:00Z", expires_at: "2026-10-18T10:00:00Z", revoked_at: null };
describe("settings presentation", () => {
  for (const held of ["read", "launch", "admin"] as const) for (const role of ["read", "launch", "admin"] as const) test(`${held} issuing to ${role} cannot widen either ceiling`, () => {
    const order: Scope[] = ["read", "launch", "admin"]; const scopes = allowedScopes({ ...principal, scope: held }, { ...user, role });
    expect(scopes).toEqual(order.slice(0, Math.min(order.indexOf(held), order.indexOf(role)) + 1));
  });
  test("disabled and other-user offers are refused", () => { expect(allowedScopes(principal, { ...user, disabled_at: "2026-01-01" })).toEqual([]); expect(allowedScopes({ ...principal, scope: "launch" }, { ...user, name: "bob" })).toEqual([]); });
  test("all existing names remain reserved including disabled", () => { expect(validUser("alice", [{ ...user, disabled_at: "2026-01-01" }])).toBe(false); for (const name of ["A", "_a", "a b", "a".repeat(33), ""]) expect(validUser(name)).toBe(false); expect(validUser("a-b_12")).toBe(true); });
  test("expiry boundary, revocation, invalid dates", () => { expect(sessionState(session, now)).toBe("active"); expect(sessionState({ ...session, expires_at: new Date(now).toISOString() }, now)).toBe("expired"); expect(sessionState({ ...session, expires_at: "bad" }, now)).toBe("unknown"); expect(sessionState({ ...session, revoked_at: "yesterday" }, now)).toBe("revoked"); expect(activeSessions([session, { ...session, revoked_at: "yes" }], "alice", now)).toBe(1); });
  test("relative times and distinct send states", () => { expect(lastSeen("bad", now)).toBe("—"); expect(lastSeen(session.last_seen_at, now)).toBe("1m ago"); expect(new Set(["pending", "sending", "sent", "failed", "skipped"].map(noticeGlyph)).size).toBe(5); expect(clientLabel("cli")).toBe("CLI"); });
});

test("scope glyphs, observed current session and digest schedule", () => { expect(scopeGlyph("admin")).toBe("a"); expect(currentSession(session, principal)).toBe(true); expect(eventGlyph("finished")).toBe("✓"); expect(digestSchedule({ enabled: true, weekday: "mon", hour: 9, timezone: null, channels: [], projects: "all", save_to_notebook: true, top_notes: 5 })).toBe("mon 9:00 · hub local timezone"); });
