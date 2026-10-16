import { afterEach, beforeEach, expect, test } from "bun:test";
import { cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { auth } from "../../src/api/auth";
import type { CleanPlan, CleanPolicy } from "../../src/api/models";
import { StoragePage } from "../../src/pages/Storage";
import { Clean } from "../../src/pages/storage/Clean";
import { mockApi, restoreFetch, renderWithClient } from "../pages/helpers";
const policy: CleanPolicy = { archived: true, older_than_days: 30, kinds: ["checkpoint"], projects: null, hosts: null, include_pulled: true };
const item = { project: "p", run_id: "r", host: "local", environment_id: "local-id", kind: "artifact" as const, artifact_kind: "checkpoint", path: "/artifact", bytes: 96400000000, mtime: 1, reason: "eligible" };
const items = [item, { ...item, path: "/artifact-two", bytes: 74000000000 }, { ...item, path: "/changed", bytes: 241900000000 }];
const plan = (): CleanPlan => ({ plan_id: "cp-12345678", policy, items, refused: [{ path: "/protected", reason: "protected" }], total_bytes: 412300000000, created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60000).toISOString(), created_by: "local" });
beforeEach(() => { auth.accept(auth.select(null)); }); afterEach(() => { cleanup(); auth.select(null); restoreFetch(); });
test("storage nonadmin never fetches a report", async () => { const calls = mockApi({ "GET /api/v1/auth/me": { auth: "on", scope: "read", scopes: ["read"], user: "alice", session_id: "s", client: "browser", public_url: null } }); const view = renderWithClient(<StoragePage />); await view.findByText("Storage requires admin scope."); expect(calls).toHaveLength(1); });
test("exact bytes gate, frozen plan and partial response", async () => { const p = plan(); const calls = mockApi({ "POST /api/v1/storage/plan": p, "POST /api/v1/storage/plans/cp-12345678/apply": { plan_id: p.plan_id, deleted: p.items.slice(0, 2), skipped: [{ path: "/changed", reason: "changed since plan" }], errors: [], freed_bytes: 170400000000 } }); const view = renderWithClient(<Clean ready />); expect(view.queryByRole("button", { name: "Apply" })).toBeNull(); fireEvent.click(view.getByRole("button", { name: "Dry run" })); fireEvent.click(await view.findByRole("button", { name: "Apply" })); const dialog = within(view.getByRole("dialog", { name: "Apply cleanup" })); fireEvent.change(dialog.getByLabelText("Confirm bytes"), { target: { value: "412.3" } }); expect((dialog.getByRole("button", { name: "Apply" }) as HTMLButtonElement).disabled).toBe(true); fireEvent.change(dialog.getByLabelText("Confirm bytes"), { target: { value: "412300000000" } }); fireEvent.click(dialog.getByRole("button", { name: "Apply" })); await view.findByText(/Freed 170.4 GB/); expect(view.getByText(/changed since plan/)).toBeTruthy(); expect(calls.find((c) => c.url.endsWith("/apply"))?.body).toMatchObject({ confirm_bytes: 412300000000 }); });
test("policy changes discard the old plan", async () => { mockApi({ "POST /api/v1/storage/plan": plan() }); const view = renderWithClient(<Clean ready />); fireEvent.click(view.getByRole("button", { name: "Dry run" })); await view.findByText("Plan cp-12345678"); fireEvent.change(view.getByLabelText("Older than (days)"), { target: { value: "40" } }); await waitFor(() => expect(view.queryByText("Plan cp-12345678")).toBeNull()); });
test("expired and unsafe server plans cannot apply", async () => { mockApi({ "POST /api/v1/storage/plan": { ...plan(), expires_at: "2020-01-01" } }); const view = renderWithClient(<Clean ready />); fireEvent.click(view.getByRole("button", { name: "Dry run" })); const apply = await view.findByRole("button", { name: "Apply" }); expect((apply as HTMLButtonElement).disabled).toBe(true); });
test("stale dry-run completion is discarded after auth replacement", async () => { let resolve!: (v: unknown) => void; mockApi({ "POST /api/v1/storage/plan": () => new Promise((r) => { resolve = r; }) }); const view = renderWithClient(<Clean ready />); fireEvent.click(view.getByRole("button", { name: "Dry run" })); await waitFor(() => expect(resolve).toBeDefined()); auth.select(null); resolve(plan()); await new Promise((r) => setTimeout(r, 10)); expect(view.queryByText("Plan cp-12345678")).toBeNull(); });
test("network retries reuse exact command id and snapshot", async () => { let n = 0; const calls = mockApi({ "POST /api/v1/storage/plan": () => { if (++n === 1) throw new Error("connection dropped"); return plan(); } }); const view = renderWithClient(<Clean ready />); fireEvent.click(view.getByRole("button", { name: "Dry run" })); await view.findByText("Plan cp-12345678"); expect(calls).toHaveLength(2); expect(calls[0].body).toEqual(calls[1].body); });
test("dialog rechecks expiry without reopening", async () => { mockApi({ "POST /api/v1/storage/plan": { ...plan(), expires_at: new Date(Date.now() + 700).toISOString() } }); const view = renderWithClient(<Clean ready />); fireEvent.click(view.getByRole("button", { name: "Dry run" })); fireEvent.click(await view.findByRole("button", { name: "Apply" })); const dialog = within(view.getByRole("dialog", { name: "Apply cleanup" })); fireEvent.change(dialog.getByLabelText("Confirm bytes"), { target: { value: "412300000000" } }); await waitFor(() => expect((dialog.getByRole("button", { name: "Apply" }) as HTMLButtonElement).disabled).toBe(true), { timeout: 2000 }); expect(dialog.getByText("Plan expired. Create a new dry run.")).toBeTruthy(); });
test("pending deletion disables close and duplicate submission", async () => { let resolve!: (v: unknown) => void; const p = plan(); const calls = mockApi({ "POST /api/v1/storage/plan": p, "POST /api/v1/storage/plans/cp-12345678/apply": () => new Promise((r) => { resolve = r; }) }); const view = renderWithClient(<Clean ready />); fireEvent.click(view.getByRole("button", { name: "Dry run" })); fireEvent.click(await view.findByRole("button", { name: "Apply" })); const dialog = within(view.getByRole("dialog", { name: "Apply cleanup" })); fireEvent.change(dialog.getByLabelText("Confirm bytes"), { target: { value: "412300000000" } }); fireEvent.click(dialog.getByRole("button", { name: "Apply" })); await waitFor(() => expect(resolve).toBeDefined()); expect((dialog.getByRole("button", { name: "Close" }) as HTMLButtonElement).disabled).toBe(true); fireEvent.keyDown(view.getByRole("dialog"), { key: "Escape" }); expect(view.getByRole("dialog")).toBeTruthy(); expect(calls.filter((c) => c.url.endsWith("/apply"))).toHaveLength(1); resolve({ plan_id: p.plan_id, deleted: [], skipped: [], errors: [], freed_bytes: 0 }); await view.findByRole("region", { name: "Cleanup result" }); });

test("shared-path cleanup shows each owner and uses the physical byte total", async () => {
  const shared = ["first", "second"].map((run_id) => ({ ...item, run_id, bytes: 4096 }));
  const p = { ...plan(), items: shared, refused: [], total_bytes: 4096 };
  const calls = mockApi({
    "POST /api/v1/storage/plan": p,
    "POST /api/v1/storage/plans/cp-12345678/apply": {
      plan_id: p.plan_id, deleted: shared, skipped: [], errors: [], freed_bytes: 4096,
    },
  });
  const view = renderWithClient(<Clean ready />);
  fireEvent.click(view.getByRole("button", { name: "Dry run" }));
  fireEvent.click(await view.findByRole("button", { name: "Apply" }));
  const dialog = within(view.getByRole("dialog", { name: "Apply cleanup" }));
  expect(dialog.getByText("2 items · 1 environments · 0 refused")).toBeTruthy();
  fireEvent.change(dialog.getByLabelText("Confirm bytes"), { target: { value: "4096" } });
  fireEvent.click(dialog.getByRole("button", { name: "Apply" }));
  const result = within(await view.findByRole("region", { name: "Cleanup result" }));
  expect(result.getByText(/Freed .* · 4096 bytes/)).toBeTruthy();
  expect(result.getByText(/first · local · local-id · \/artifact · 4096 bytes/)).toBeTruthy();
  expect(result.getByText(/second · local · local-id · \/artifact · 4096 bytes/)).toBeTruthy();
  expect(calls.find((c) => c.url.endsWith("/apply"))?.body).toMatchObject({ confirm_bytes: 4096 });
});
