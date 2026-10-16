import { afterEach, beforeEach, expect, setSystemTime, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { QueuePage } from "../../src/hosts/QueuePage";
import { HOSTS } from "../api/phase2-fixtures";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { NOW, pendingRecord, queuedRecord } from "../pages/remoteFixtures";

beforeEach(() => setSystemTime(new Date(NOW)));
afterEach(() => {
  cleanup();
  restoreFetch();
  setSystemTime();
});

const QUEUE = "GET /api/v1/runs?status=queued&limit=1000";

test("queued runs per host with position, launcher, GPUs, wait and status", async () => {
  mockApi({ [QUEUE]: [queuedRecord(), pendingRecord()], "GET /api/v1/hosts": HOSTS });
  renderWithClient(<QueuePage />);
  expect(await screen.findByRole("heading", { name: "Queue" })).toBeTruthy();
  const gpu1 = await screen.findByRole("region", { name: "gpu1" });
  const rows = within(gpu1).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(1);
  expect(rows[0]?.textContent).toContain("queued");
  expect(within(rows[0]!).getByText("tuner")).toBeTruthy();
  expect(within(rows[0]!).getByText("12m")).toBeTruthy();
  expect(screen.getByRole("region", { name: "mccleary" })).toBeTruthy();
  expect(screen.getByText("2 queued on 2 hosts")).toBeTruthy();
});

test("Stop needs a second click and stops only a queued run", async () => {
  const id = queuedRecord().run_id;
  const calls = mockApi({ [QUEUE]: [queuedRecord()], "GET /api/v1/hosts": HOSTS, [`POST /api/v1/runs/${id}/stop`]: { ...queuedRecord(), status: "killed" } });
  renderWithClient(<QueuePage />);
  const stop = await screen.findByRole("button", { name: "Stop" });
  fireEvent.click(stop);
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Stop ✓?" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(1));
  expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ only_queued: true, created_by: "human" });
});

test("an empty queue says so", async () => {
  mockApi({ [QUEUE]: [], "GET /api/v1/hosts": HOSTS });
  renderWithClient(<QueuePage />);
  expect(await screen.findByText("Nothing queued")).toBeTruthy();
});
