import { afterEach, beforeEach, expect, setSystemTime, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { clearLostReasons, noteLostReasons } from "../../src/api/lostReasons";
import { RunPage } from "../../src/pages/Run";
import { DGX_STATE, HOSTS } from "../api/phase2-fixtures";
import { HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";
import {
  LOST_ID,
  NOW,
  QUEUED_ID,
  RUNNING_ID,
  STALE_ID,
  lostRecord,
  queuedRecord,
  remoteDetail,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

beforeEach(() => {
  setSystemTime(new Date(NOW));
});

afterEach(() => {
  cleanup();
  restoreFetch();
  setSystemTime();
  clearLostReasons();
});

const registry = fakeRegistry(["curves"]);
const HOSTS_ROUTE = "GET /api/v1/hosts";
const ENV_ROUTE = "GET /.well-known/hypothex/environment";
/** This hub's descriptor: its id starts with `0a1b2c3d`, the owner in `sweep:0a1b2c3d:s-7f3a`. */
const HUB_ENV = { environment_id: "0a1b2c3d4e5f60718293a4b5c6d7e8f9", label: "hub", hx_version: "0.5.0" };
const QUEUE_URL = "/api/v1/runs?status=queued&environment_id=env-gpu1&limit=1000";
const QUEUE_ROUTE = `GET ${QUEUE_URL}`;

const regionNames = () => screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
const statValues = () => [...document.querySelectorAll(".stats dd")].map((d) => d.textContent);

test("a queued run: title with its place, the host queue, placement", async () => {
  const behind = queuedRecord({
    run_id: "20261003-142500-toy-test-93e7",
    hypothesis: "lr 1e-3 with beam 5",
    created_at: "2026-10-03T14:25:00Z",
    executor: { ...queuedRecord().executor, queue_position: 3 },
  });
  const calls = mockApi({
    [`GET /api/v1/runs/${QUEUED_ID}`]: remoteDetail(queuedRecord()),
    [HOSTS_ROUTE]: HOSTS,
    [QUEUE_ROUTE]: [behind, queuedRecord()],
  });
  renderWithClient(<RunPage runId={QUEUED_ID} />, { registry });
  // the host is named once the hosts list matches the run's environment (executor.host is sv-a100-01)
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toBe("lr 1e-3 with beam 1 · seed 3: queued 2nd on gpu1"));
  await waitFor(() => expect(statValues()).toEqual(["2 / 3", "2 GPU", "1 / 3", "12m"]));
  await waitFor(() => expect(document.querySelectorAll(".queue-t tbody tr").length).toBe(2));
  expect(regionNames()).toEqual(["a Queue", "b Where", "c Placement", "d Scores", "e Notes"]);
  expect(document.querySelector('.queue-t tr[aria-current="true"] b')?.textContent).toBe("f2c8");
  expect(document.querySelector(".status")?.textContent).toContain("2 of 3 on gpu1");
  expect(screen.getAllByRole("button").map((b) => b.textContent)).toContain("Cancel");
  expect(new Set(calls.map((c) => c.url))).toEqual(
    new Set([`/api/v1/runs/${QUEUED_ID}`, "/api/v1/hosts", QUEUE_URL]),
  );
});

test("a long queue: every page is read, the head is kept, and the run shows even if the list lacks it", async () => {
  // 1,200 runs wait on gpu1 ahead of and behind this one; the first page (1,000) is full
  const behind = Array.from({ length: 1200 }, (_, i) =>
    queuedRecord({
      run_id: `20261003-1430${String(i).padStart(4, "0")}-toy-test-q${i}`,
      created_at: "2026-10-03T14:30:00Z",
      executor: { ...queuedRecord().executor, queue_position: i < 1 ? 1 : i + 2 },
    }),
  );
  const last = behind.at(-1);
  const cursor = `before_created_at=${encodeURIComponent(last?.created_at ?? "")}&before_run_id=${last?.run_id}`;
  const nextUrl = `${QUEUE_URL.replace("limit=1000", "limit=4000")}&${cursor}`;
  const calls = mockApi({
    [`GET /api/v1/runs/${QUEUED_ID}`]: remoteDetail(queuedRecord()),
    [HOSTS_ROUTE]: HOSTS,
    // the hub answers newest first, so the head (position 1) is on the second (keyset) page
    [QUEUE_ROUTE]: behind.slice(200),
    [`GET ${nextUrl}`]: behind.slice(0, 200),
  });
  renderWithClient(<RunPage runId={QUEUED_ID} />, { registry });
  await waitFor(() => expect(document.querySelectorAll(".queue-t tbody tr").length).toBe(1201));
  const positions = [...document.querySelectorAll(".queue-t tbody tr")].slice(0, 3).map((r) => r.querySelector("td")?.textContent);
  expect(positions).toEqual(["1", "2", "3"]);
  // this run is in neither page (read before it was indexed), yet it is listed and marked
  expect(document.querySelector('.queue-t tr[aria-current="true"] b')?.textContent).toBe("f2c8");
  expect(calls.filter((c) => c.url.startsWith("/api/v1/runs?")).map((c) => c.url)).toEqual([
    QUEUE_URL,
    nextUrl,
  ]);
});

test("a running remote run: host, pid, GPU use, CUDA_VISIBLE_DEVICES", async () => {
  mockApi({ [`GET /api/v1/runs/${RUNNING_ID}`]: remoteDetail(runningRecord()), [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={RUNNING_ID} />, { registry });
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("aug long run seed 1");
  await waitFor(() => expect(statValues()).toEqual(["1h 52m", "92 %", "57 GB", "1.87"]));
  expect(regionNames()).toEqual(["a Where", "b Placement", "c Scores", "d Notes"]);
  expect(screen.getByRole("region", { name: "b Placement" }).textContent).toContain("CUDA_VISIBLE_DEVICES=0");
  expect(document.querySelector(".status")?.textContent).toContain("gpu1, pid 2291045");
});

test("a run on an unreachable host: stale since, bar, Reconnect", async () => {
  const calls = mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: HOSTS,
    "POST /api/v1/hosts/dgx/connect": { ...DGX_STATE, state: "connecting" },
  });
  renderWithClient(<RunPage runId={STALE_ID} />, { registry });
  await waitFor(() =>
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("lr 1e-3 with beam 10: stale since 14:28"),
  );
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx unreachable 5m");
  expect(statValues()).toEqual(["3h 30m", "7.00", "5m"]);
  expect(document.querySelector(".status .st")?.textContent).toBe("stale");
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/hosts/dgx/connect")).toBe(true));
});

test("elapsed times tick with the clock even when a refetch returns the same data", async () => {
  mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: HOSTS,
  });
  const { client } = renderWithClient(<RunPage runId={STALE_ID} clockMs={20} />, { registry });
  await waitFor(() => expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx unreachable 5m"));
  // ten minutes on; the host still does not answer, so every poll returns the same body
  setSystemTime(new Date(NOW + 10 * 60_000));
  await client.refetchQueries();
  await waitFor(() => expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx unreachable 15m"));
  expect(statValues().at(-1)).toBe("15m");
});

test("the tunnel dies mid-mirror: the hosts list fails, the page still says stale", async () => {
  let up = true;
  const calls = mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: () =>
      up ? HOSTS : new HttpReply(503, { error: "dgx: tunnel closed", type: "HostUnavailableError" }),
    "POST /api/v1/hosts/dgx/connect": { ...DGX_STATE, state: "connecting" },
  });
  const { client } = renderWithClient(<RunPage runId={STALE_ID} />, { registry });
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toBe("lr 1e-3 with beam 10: stale since 14:28"));
  up = false;
  await client.refetchQueries({ queryKey: ["hosts"] });
  expect(calls.filter((c) => c.url === "/api/v1/hosts").length).toBeGreaterThanOrEqual(2);
  // the failed refetch keeps the last list: same host, same bar, Reconnect still names dgx
  expect(h1.textContent).toBe("lr 1e-3 with beam 10: stale since 14:28");
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx unreachable 5m");
  expect(document.querySelector(".status .st")?.textContent).toBe("stale");
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/hosts/dgx/connect")).toBe(true));
});

test("opened while the hosts list fails: stale, the machine's hostname, Reconnect disabled", async () => {
  mockApi({
    [`GET /api/v1/runs/${STALE_ID}`]: remoteDetail(staleRecord(), "stale"),
    [HOSTS_ROUTE]: new HttpReply(503, { error: "dgx: tunnel closed", type: "HostUnavailableError" }),
  });
  renderWithClient(<RunPage runId={STALE_ID} />, { registry });
  // no hosts list: the run is still stale (host_state), named by its machine's own hostname
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe(
    "lr 1e-3 with beam 10: dgx-h100-07 unreachable",
  );
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("dgx-h100-07 unreachable");
  expect(statValues()).toEqual(["3h 30m", "7.00"]);
  expect(document.querySelector(".status .st")?.textContent).toBe("stale");
  // the hub's name for the host is unknown, so Reconnect cannot be sent
  expect(screen.getByRole("button", { name: "Reconnect" }).hasAttribute("disabled")).toBe(true);
});

test("a lost SLURM run: reason bar, cost, sweep link, Rerun first", async () => {
  const record = lostRecord({ tags: ["sweep:0a1b2c3d:s-7f3a"] });
  mockApi({ [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(record), [HOSTS_ROUTE]: HOSTS, [ENV_ROUTE]: HUB_ENV });
  renderWithClient(<RunPage runId={LOST_ID} />, { registry });
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("aug long run seed 2: lost at 02:14");
  expect(screen.getByRole("status").querySelector("b")?.textContent).toBe("SLURM job 4471023 lost");
  expect(statValues()).toEqual(["52m 27s", "$2.17"]);
  expect(regionNames()).toEqual(["a Where", "b Placement", "c Scores", "d Notes"]);
  const link = await screen.findByRole("link", { name: "sweep s-7f3a" });
  expect(link.getAttribute("href")).toBe("/s/toy-classifier/s-7f3a");
  expect(screen.getByRole("button", { name: "Rerun" }).className).toBe("btn primary");
  await waitFor(() =>
    expect(screen.getByRole("region", { name: "b Placement" }).textContent).toContain("r814u05n01"),
  );
});

test("a run of another hub's sweep names the sweep without a link", async () => {
  // a host shared by two hubs: the run's tag names the other hub (ffffffff), whose sweep
  // s-7f3a this hub has no page for (or has a different sweep under that id)
  const record = lostRecord({ tags: ["sweep:ffffffff:s-7f3a"] });
  mockApi({ [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(record), [HOSTS_ROUTE]: HOSTS, [ENV_ROUTE]: HUB_ENV });
  renderWithClient(<RunPage runId={LOST_ID} />, { registry });
  const crumb = await screen.findByTitle("sweep of another hub (ffffffff)");
  expect(crumb.textContent).toBe("sweep s-7f3a");
  expect(screen.queryByRole("link", { name: "sweep s-7f3a" })).toBeNull();
});

test("a lost run shows the reason its mirrored run.lost event carried", async () => {
  const why = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";
  noteLostReasons([
    {
      sequence: 41,
      type: "mirror.run_updated",
      project: "toy-classifier",
      run_id: LOST_ID,
      payload: { host: "mccleary", original_type: "run.lost", status: "lost", reason: why },
      created_at: "2026-10-03T02:14:40Z",
    },
  ]);
  mockApi({ [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(lostRecord()), [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={LOST_ID} />, { registry });
  await screen.findByRole("heading", { level: 1 });
  const bar = screen.getByRole("status");
  expect(bar.querySelector("b")?.textContent).toBe("SLURM job 4471023 lost");
  expect(bar.querySelector("span")?.textContent).toBe(why);
});

test("an unmapped active environment is never treated as a hub run and cannot reconnect", async () => {
  const detail = remoteDetail(runningRecord({ environment_id: "env-removed" }), null);
  const calls = mockApi({ [`GET /api/v1/runs/${RUNNING_ID}`]: { ...detail, served: false }, [HOSTS_ROUTE]: HOSTS });
  renderWithClient(<RunPage runId={RUNNING_ID} />, { registry });
  const reconnect = await screen.findByRole("button", { name: "Reconnect" });
  await waitFor(() => expect(reconnect.title).toContain("No configured host"));
  expect(reconnect.hasAttribute("disabled")).toBe(true);
  fireEvent.click(reconnect);
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
});

test("persisted lost reason is visible on a fresh run page with no event cache", async () => {
  mockApi({ [`GET /api/v1/runs/${LOST_ID}`]: remoteDetail(lostRecord({ end_reason: "NODE_FAIL" })), [HOSTS_ROUTE]: HOSTS, [ENV_ROUTE]: HUB_ENV });
  renderWithClient(<RunPage runId={LOST_ID} />, { registry });
  expect(await screen.findByText("NODE_FAIL")).toBeTruthy();
  expect(document.querySelector(".state-bar b")?.getAttribute("title")).toContain("persisted");
});
