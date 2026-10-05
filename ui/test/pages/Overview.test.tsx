import { afterEach, expect, test } from "bun:test";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { queryKeys } from "../../src/api/queries";
import { OverviewPage } from "../../src/pages/Overview";
import { makeOverview } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";
import { RUN_AGENT, asSent, localRow, makeHostRuns, makeHosts } from "./hostFixtures";
import { OVERVIEW_COST } from "../api/phase2-fixtures";

const ENV = "GET /.well-known/hypothex/environment";

afterEach(() => {
  cleanup();
  restoreFetch();
});

test("only the hub's own row: backend headline and counts, panels a-f", async () => {
  // the backend's host_rows always sends the hub itself; with no other host nothing changes
  mockApi({ "GET /api/v1/overview": makeOverview(), "GET /api/v1/hosts": [localRow()], [ENV]: { hx_version: "0.5.0" } });
  renderWithClient(<OverviewPage />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  const hostsPanel = screen.getByRole("region", { name: "a Hosts" });
  const hub = await within(hostsPanel).findByRole("group", { name: "local" });
  expect(hub.querySelector(".kind")?.textContent).toBe("hub");
  expect(h1.textContent).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
  for (const text of ["19 runs today", "3 failed", "1 task"]) expect(screen.getByText(text)).toBeTruthy();
  expect(document.querySelector(".hosts-banner")).toBeNull();
  const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
  expect(names).toEqual(["a Hosts", "b Runs by launcher", "c Ideas", "d Running", "e Failures", "f Projects"]);
  expect(within(screen.getByRole("region", { name: "d Running" })).getByText("none")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "f Projects" })).getByText("0.9222")).toBeTruthy();
});

test("with hosts: running/waiting from the backend, stale from hosts; metaline and cells", async () => {
  const summary = { ...makeOverview(), counts: { running: 12, queued: 11 }, running: makeHostRuns() };
  mockApi({
    "GET /api/v1/overview": summary,
    "GET /api/v1/hosts": [localRow(), ...asSent(makeHosts(Date.now()))],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toBe("12 running, 11 waiting. dgx stale 4m"));
  expect(await screen.findByText("hub hx 0.5.0")).toBeTruthy();
  const meta = [...document.querySelectorAll(".metaline span")].map((s) => s.textContent);
  // 5 hosts: one per row of the Hosts table, the hub's own row too
  expect(meta).toEqual(["1 GPU free", "$332 today", "hub hx 0.5.0", "5 hosts"]);
  const panel = screen.getByRole("region", { name: "a Hosts" });
  expect(panel.querySelector(".aside")?.textContent).toBe("$332 today");
  expect(within(panel).getAllByRole("group").map((g) => g.getAttribute("aria-label"))).toEqual([
    "local",
    "gpu1",
    "dgx",
    "mccleary",
    "gpu2",
  ]);
  const gpu1 = within(panel).getByRole("group", { name: "gpu1" });
  expect(within(gpu1).getAllByRole("link")[0]?.getAttribute("href")).toBe(`/r/${RUN_AGENT}`);
  expect(within(gpu1).getByTitle("hub runs hx 0.5.0. Update: hx hosts upgrade gpu1")).toBeTruthy();
  expect(document.querySelector(".hosts-banner")).toBeNull();
});

test("a host stale for more than 24 h gets a banner; it is still stale, not lost", async () => {
  const now = Date.now();
  const hosts = asSent(makeHosts(now)).map((h) =>
    h.name === "dgx" ? { ...h, state: { ...h.state, since: new Date(now - 26 * 3_600_000).toISOString() } } : h,
  );
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), counts: { running: 1, queued: 0 } },
    "GET /api/v1/hosts": [localRow(), ...hosts],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await waitFor(() => expect(document.querySelector(".hosts-banner")?.textContent).toBe("dgx unreachable 1d"));
  const banner = document.querySelector(".hosts-banner") as HTMLElement;
  expect(banner.getAttribute("role")).toBe("status");
  expect(banner.getAttribute("title")).toBe(
    "No answer for more than 24 h. Its runs stay stale, not lost: only the host marks a run lost.",
  );
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("1 running. dgx stale 1d");
});

test("the banner threshold is the hub's stale_banner_hours", async () => {
  const now = Date.now();
  // dgx stale for 7 h: no banner at the default 24 h, a banner with stale_banner_hours 6
  const hosts = asSent(makeHosts(now)).map((h) =>
    h.name === "dgx" ? { ...h, state: { ...h.state, since: new Date(now - 7 * 3_600_000).toISOString() } } : h,
  );
  const six = [localRow({ stale_banner_hours: 6 }), ...hosts.map((h) => ({ ...h, stale_banner_hours: 6 }))];
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), counts: { running: 1, queued: 0 } },
    "GET /api/v1/hosts": six,
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await waitFor(() => expect(document.querySelector(".hosts-banner")?.textContent).toBe("dgx unreachable 7h"));
  expect(document.querySelector(".hosts-banner")?.getAttribute("title")).toBe(
    "No answer for more than 6 h. Its runs stay stale, not lost: only the host marks a run lost.",
  );
  cleanup();
  restoreFetch();
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), counts: { running: 1, queued: 0 } },
    "GET /api/v1/hosts": [localRow(), ...hosts],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("1 running. dgx stale 7h"));
  expect(document.querySelector(".hosts-banner")).toBeNull();
});

test("cost today comes from the overview when it sends it; the hub-only metaline shows it too", async () => {
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), ...OVERVIEW_COST, counts: { running: 12, queued: 11 } },
    "GET /api/v1/hosts": [localRow(), ...asSent(makeHosts(Date.now()))],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  // $402.75 of every run today, hub runs included (the hosts alone sum to $331.60)
  await waitFor(() =>
    expect([...document.querySelectorAll(".metaline span")].map((s) => s.textContent)).toEqual([
      "1 GPU free",
      "$403 today",
      "hub hx 0.5.0",
      "5 hosts",
    ]),
  );
  expect(screen.getByRole("region", { name: "a Hosts" }).querySelector(".aside")?.textContent).toBe("$403 today");
  cleanup();
  restoreFetch();
  mockApi({
    "GET /api/v1/overview": { ...makeOverview(), cost_today_usd: 12.25 },
    "GET /api/v1/hosts": [localRow()],
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  await screen.findByRole("heading", { level: 1 });
  const meta = () => [...document.querySelectorAll(".metaline span")].map((s) => s.textContent);
  // the phase 1 counts, then the cost of today's runs (also the Hosts panel's aside)
  await waitFor(() => expect(meta()).toContain("$12 today"));
  expect(meta()).toContain("19 runs today");
  expect(meta().at(-1)).toBe("$12 today");
});

test("hosts endpoint fails: error inside the Hosts panel, the rest of the page stays", async () => {
  mockApi({
    "GET /api/v1/overview": makeOverview(),
    "GET /api/v1/hosts": new HttpReply(500, { error: "hub offline", type: "HostUnavailableError" }),
    [ENV]: { hx_version: "0.5.0" },
  });
  renderWithClient(<OverviewPage />);
  const panel = await screen.findByRole("region", { name: "a Hosts" });
  expect((await within(panel).findByRole("alert")).textContent).toBe("hub offline");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
  expect(screen.getByRole("region", { name: "c Ideas" })).toBeTruthy();
});

test("hosts refetch fails after a good load: old rows do not drive the headline or metaline", async () => {
  // TanStack Query keeps the last good data when a later poll fails
  let fail = false;
  const summary = { ...makeOverview(), counts: { running: 12, queued: 11 }, running: makeHostRuns() };
  const good = [localRow(), ...asSent(makeHosts(Date.now()))];
  mockApi({
    "GET /api/v1/overview": summary,
    "GET /api/v1/hosts": () => (fail ? new HttpReply(500, { error: "hub offline", type: "HostUnavailableError" }) : good),
    [ENV]: { hx_version: "0.5.0" },
  });
  const { client } = renderWithClient(<OverviewPage />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(h1.textContent).toBe("12 running, 11 waiting. dgx stale 4m"));
  fail = true;
  await client.refetchQueries({ queryKey: queryKeys.hosts() });
  const panel = screen.getByRole("region", { name: "a Hosts" });
  expect((await within(panel).findByRole("alert")).textContent).toBe("hub offline");
  expect(client.getQueryData(queryKeys.hosts())).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
  const meta = [...document.querySelectorAll(".metaline span")].map((s) => s.textContent);
  expect(meta).toEqual(["12 running", "11 queued"]);
  expect(panel.querySelector(".aside")).toBeNull();
  expect(document.querySelector(".hosts-banner")).toBeNull();
});

test("shows the server error", async () => {
  mockApi({ "GET /api/v1/overview": new HttpReply(500, { error: "index locked", type: "StoreError" }) });
  renderWithClient(<OverviewPage />);
  expect((await screen.findByRole("alert")).textContent).toBe("index locked");
});
