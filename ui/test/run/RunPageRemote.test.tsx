// The old RunRemote behaviours on the v5 run page.
import { afterEach, beforeEach, expect, setSystemTime, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { clearLostReasons } from "../../src/api/lostReasons";
import { RunPage } from "../../src/run/RunPage";
import { DGX_STATE, HOSTS } from "../api/phase2-fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import {
  LOST_ID, NOW, QUEUED_ID, RUNNING_ID, STALE_ID, lostRecord, queuedRecord, remoteDetail, runningRecord, staleRecord,
} from "../pages/remoteFixtures";
import { propValue } from "./ctx";

beforeEach(() => setSystemTime(new Date(NOW)));
afterEach(() => {
  cleanup();
  restoreFetch();
  setSystemTime();
  clearLostReasons();
});

const HOSTS_ROUTE = "GET /api/v1/hosts";
const QUEUE_ROUTE = "GET /api/v1/runs?status=queued&environment_id=env-gpu1&limit=1000";
const HUB_ENV = { environment_id: "0a1b2c3d4e5f60718293a4b5c6d7e8f9", label: "hub", hx_version: "0.5.0" };

test("a queued run: queued bar, the host queue, Queue place in the sidebar, only Cancel", async () => {
  mockApi({ [`GET /api/v1/runs/${QUEUED_ID}`]: remoteDetail(queuedRecord()), [HOSTS_ROUTE]: HOSTS, [QUEUE_ROUTE]: [queuedRecord()] });
  renderWithClient(<RunPage runId={QUEUED_ID} />);
  await waitFor(() => expect(screen.getByRole("status").firstElementChild?.textContent).toBe("Queued 2nd of 3 on gpu1"));
  await waitFor(() => expect(document.querySelectorAll(".queue-t tbody tr")).toHaveLength(1));
  expect(propValue("Queue")).toContain("2 of 3");
  expect(screen.getByRole("button", { name: "Cancel" }).className).toBe("btn primary");
  expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
});

test("a running remote run: host, PID, GPUs as CUDA_VISIBLE_DEVICES with copy, GPU use", async () => {
  mockApi({ [`GET /api/v1/runs/${RUNNING_ID}`]: remoteDetail(runningRecord()), [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={RUNNING_ID} />);
  await waitFor(() => expect(propValue("Host")).toBe("gpu1 · ssh"));
  expect(propValue("PID")).toBe("2291045");
  expect(propValue("GPUs")).toContain("CUDA_VISIBLE_DEVICES=0");
  expect(screen.getByRole("button", { name: "Copy GPUs CUDA_VISIBLE_DEVICES=0" })).toBeTruthy();
  expect(propValue("GPU use")).toMatch(/% · \d+ GB$/);
});

test("a run on an unreachable host: stale pill and bar, Reconnect posts to the hub's host name", async () => {
  const calls = mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: HOSTS,
    "POST /api/v1/hosts/dgx/connect": { ...DGX_STATE, state: "connecting" },
  });
  renderWithClient(<RunPage runId={STALE_ID} />);
  await waitFor(() => expect(screen.getByRole("status").firstElementChild?.textContent).toBe("dgx unreachable 5m"));
  expect(document.querySelector(".rhead .pill")?.textContent).toContain("Stale");
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/hosts/dgx/connect")).toBe(true));
});

test("the hosts list fails: still stale, the machine's hostname, Reconnect disabled", async () => {
  mockApi({ [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"), [HOSTS_ROUTE]: new HttpReply(502, { error: "tunnel down", type: "HostUnavailableError" }) });
  renderWithClient(<RunPage runId={STALE_ID} />);
  await waitFor(() => expect(screen.getByRole("status").firstElementChild?.textContent).toBe("dgx-h100-07 unreachable"));
  expect(screen.getByRole("button", { name: "Reconnect" }).hasAttribute("disabled")).toBe(true);
});

test("a lost SLURM run: reason bar, Rerun first, cost and sweep link in the sidebar", async () => {
  mockApi({
    [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(lostRecord({ tags: ["sweep:0a1b2c3d:s-7f3a"] })),
    [HOSTS_ROUTE]: HOSTS,
    "GET /.well-known/hypothex/environment": HUB_ENV,
  });
  renderWithClient(<RunPage runId={LOST_ID} />);
  await waitFor(() => expect(screen.getByRole("status").firstElementChild?.textContent).toBe("SLURM job 4471023 lost"));
  expect(screen.getByRole("button", { name: "Rerun" }).className).toBe("btn primary");
  await waitFor(() => expect(screen.getByRole("link", { name: "s-7f3a" }).getAttribute("href")).toBe("/s/toy-classifier/s-7f3a"));
  expect(propValue("Cost")).not.toBeNull();
});

test("an unmapped active environment is never a hub run and cannot reconnect", async () => {
  mockApi({ [`GET /api/v1/runs/${RUNNING_ID}`]: { ...remoteDetail(runningRecord(), null), served: false }, [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={RUNNING_ID} />);
  const reconnect = await screen.findByRole("button", { name: "Reconnect" });
  expect(reconnect.hasAttribute("disabled")).toBe(true);
});

test("elapsed times tick with the clock even when a refetch returns the same data", async () => {
  mockApi({ [`GET /api/v1/runs/${RUNNING_ID}`]: remoteDetail(runningRecord()), [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={RUNNING_ID} clockMs={20} />);
  await waitFor(() => expect(propValue("Duration")).not.toBeNull());
  const before = propValue("Duration");
  setSystemTime(new Date(NOW + 120_000));
  await waitFor(() => expect(propValue("Duration")).not.toBe(before));
  expect(within(screen.getByRole("complementary", { name: "Properties" })).getByText("Duration")).toBeTruthy();
});

test("the Logs tab of a run shows the chosen stream", async () => {
  mockApi({
    [`GET /api/v1/runs/${RUNNING_ID}`]: remoteDetail(runningRecord()),
    [HOSTS_ROUTE]: HOSTS,
    [`GET /api/v1/runs/${RUNNING_ID}/logs?stream=stderr`]: { stream: "stderr", text: "CUDA warning\n", offset: 13, size: 13 },
  });
  renderWithClient(<RunPage runId={RUNNING_ID} log="stderr" />);
  expect(await screen.findByText("CUDA warning")).toBeTruthy();
  expect(screen.getByRole("navigation", { name: "Log stream" })).toBeTruthy();
});
