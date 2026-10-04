import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { RunActions } from "../../src/pages/components/RunActions";
import { DGX_STATE } from "../api/phase2-fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  LOST_ID,
  PENDING_ID,
  QUEUED_ID,
  lostRecord,
  pendingRecord,
  queuedRecord,
  staleRecord,
} from "./remoteFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const names = () => screen.getAllByRole("button").map((b) => b.textContent);

test("a queued run has one action: Cancel, which stops it", async () => {
  const calls = mockApi({ [`POST /api/v1/runs/${QUEUED_ID}/stop`]: { run_id: QUEUED_ID, status: "killed" } });
  renderWithClient(<RunActions record={queuedRecord()} phase="queued" hostName="gpu1" />);
  expect(names()).toEqual(["Cancel"]);
  const cancel = screen.getByRole("button", { name: "Cancel" });
  expect(cancel.className).toBe("btn primary");
  expect(cancel.getAttribute("title")).toBe("Remove from the gpu1 queue");
  fireEvent.click(cancel);
  await waitFor(() => expect(calls.length).toBe(1));
  const body = calls[0]?.body as Record<string, unknown>;
  expect(typeof body.command_id).toBe("string");
  expect(body.created_by).toBe("human");
});

test("a pending SLURM job is cancelled the same way", () => {
  mockApi({ [`POST /api/v1/runs/${PENDING_ID}/stop`]: { run_id: PENDING_ID, status: "killed" } });
  renderWithClient(<RunActions record={pendingRecord()} phase="pending" hostName="mccleary" />);
  expect(names()).toEqual(["Cancel"]);
  expect(screen.getByRole("button", { name: "Cancel" }).getAttribute("title")).toBe("Cancel SLURM job 4471031");
});

test("a stale run offers Reconnect to the hub's host name, not executor.host; Stop cannot reach the host", async () => {
  const calls = mockApi({ "POST /api/v1/hosts/dgx/connect": { ...DGX_STATE, state: "connecting" } });
  // executor.host is the box's hostname (dgx-h100-07); the hub knows the host as dgx
  renderWithClient(<RunActions record={staleRecord()} phase="stale" hostName="dgx" />);
  expect(names()).toEqual(["Reconnect", "Stop"]);
  const stop = screen.getByRole("button", { name: "Stop" });
  expect(stop.hasAttribute("disabled")).toBe(true);
  expect(stop.getAttribute("title")).toBe("dgx is unreachable");
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(calls.map((c) => c.url)).toEqual(["/api/v1/hosts/dgx/connect"]));
  expect(typeof (calls[0]?.body as Record<string, unknown>).command_id).toBe("string");
});

test("Reconnect shows the hub's error", async () => {
  mockApi({
    "POST /api/v1/hosts/dgx/connect": new HttpReply(503, { error: "dgx: ssh refused", type: "HostUnavailableError" }),
  });
  renderWithClient(<RunActions record={staleRecord()} phase="stale" hostName="dgx" />);
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  expect((await screen.findByRole("alert")).textContent).toBe("dgx: ssh refused");
});

test("without the hub's host name, Reconnect is disabled and posts nothing", () => {
  const calls = mockApi({});
  renderWithClient(<RunActions record={staleRecord()} phase="stale" hostName={null} />);
  const reconnect = screen.getByRole("button", { name: "Reconnect" });
  expect(reconnect.hasAttribute("disabled")).toBe(true);
  expect(reconnect.getAttribute("title")).toBe("The hosts list is not loaded, so the hub's name for dgx-h100-07 is unknown");
  fireEvent.click(reconnect);
  expect(calls).toEqual([]);
});

test("a lost run makes Rerun the main action", () => {
  mockApi({ [`POST /api/v1/runs/${LOST_ID}/rerun`]: { run_id: "NEW" } });
  renderWithClient(<RunActions record={lostRecord()} phase="lost" hostName="mccleary" />);
  expect(names()).toEqual(["Rerun", "Re-infer", "Re-evaluate", "Stop"]);
  expect(screen.getByRole("button", { name: "Rerun" }).className).toBe("btn primary");
  expect(screen.getByRole("button", { name: "Re-evaluate" }).className).toBe("btn");
  expect(screen.getByRole("button", { name: "Stop" }).hasAttribute("disabled")).toBe(true);
});
