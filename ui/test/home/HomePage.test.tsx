import { afterEach, expect, test } from "bun:test";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { HomePage } from "../../src/home/HomePage";
import { RUN_FAILED, makeOverview } from "../pages/fixtures";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { RUN_AGENT, makeHosts } from "../pages/hostFixtures";
import { RUNNING, makeHomeSummary, runningRecord } from "./homeFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const routes = (summary = makeHomeSummary(), hosts = makeHosts()) => ({ "GET /api/v1/overview": summary, "GET /api/v1/hosts": hosts });

test("status strip, Running now, Hosts, Tasks, Recent runs", async () => {
  const started = new Date(Date.now() - 55 * 60_000 - 5_000).toISOString();
  mockApi(routes(makeHomeSummary({ running: [runningRecord({ started_at: started })] })));
  renderWithClient(<HomePage />);
  await screen.findByRole("heading", { name: /^Tasks/ });
  expect([...document.querySelectorAll(".kpi .l")].map((l) => l.textContent)).toContain("GPUs busy");
  const running = screen.getByRole("region", { name: /^Running now/ });
  const row = within(running).getByRole("link", { name: "model svm · seed 9" });
  expect(row.getAttribute("href")).toBe(`/r/${RUNNING}`);
  // elapsed, latest step and latest primary value; no progress bar or ETA (runs report no total)
  expect(within(running).getByText("55m")).toBeTruthy();
  expect(within(running).getByText("1200")).toBeTruthy();
  expect(within(running).getByText("0.9010").getAttribute("title")).toBe("val/accuracy");
  expect(within(running).queryByRole("progressbar")).toBeNull();
  expect(within(running).queryByText("ETA")).toBeNull();
  const hosts = screen.getByRole("region", { name: /^Hosts/ });
  expect(hosts.querySelectorAll("[data-gpu]").length).toBe(7);
  expect(hosts.querySelector('[data-gpu="0"]')?.getAttribute("href")).toBe(`/r/${RUN_AGENT}`);
  expect(within(hosts).getByText("4 running · 6 pending")).toBeTruthy();
  const tasks = screen.getByRole("region", { name: /^Tasks/ });
  expect(within(tasks).getByRole("link", { name: "toy-test" }).getAttribute("href")).toBe("/t/toy-classifier/toy-test");
  expect(within(tasks).getByText("accuracy ↑")).toBeTruthy();
  expect(within(tasks).getByText("+0.0370")).toBeTruthy();
  expect(within(tasks).getByText("1 running")).toBeTruthy();
  const recent = screen.getByRole("region", { name: /^Recent runs/ });
  expect(within(recent).getByText("failed · exit 2")).toBeTruthy();
  expect(within(recent).getByRole("link", { name: "Open stderr" }).getAttribute("href")).toBe(`/r/${RUN_FAILED}?tab=logs&log=stderr`);
  expect(within(recent).getByRole("button", { name: "Copy stderr path" })).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/NaN|undefined/);
});

test("no runs yet: the empty home with the first commands and links", async () => {
  const empty = { ...makeOverview(), timeline: [], recent: [], running: [], failures: [], projects: [] };
  mockApi(routes(empty, []));
  renderWithClient(<HomePage />);
  expect(await screen.findByRole("heading", { name: "No runs yet" })).toBeTruthy();
  for (const cmd of ["hx init", 'hx run -t TASK -H "why this run exists" -- python train.py', "hx demo --with-hosts"]) {
    expect(screen.getByText(cmd)).toBeTruthy();
  }
  expect(screen.getAllByRole("link").map((a) => a.textContent)).toEqual(["Docs", "Agent skill (Claude Code, Codex)", "Add a GPU host"]);
  expect(document.body.textContent).not.toMatch(/NaN|undefined/);
});

test("a host stale for more than a day gets a banner", async () => {
  const hosts = makeHosts().map((h) => (h.name === "dgx" ? { ...h, state: { ...h.state, since: "2026-09-20T00:00:00Z" } } : h));
  mockApi(routes(makeHomeSummary(), hosts));
  renderWithClient(<HomePage />);
  await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/^dgx unreachable \d+d$/));
});

test("a hosts failure stays inside the Hosts section; an overview failure is shown", async () => {
  mockApi({ "GET /api/v1/overview": makeHomeSummary() });
  const view = renderWithClient(<HomePage />);
  await screen.findByRole("heading", { name: /^Tasks/ });
  const hosts = screen.getByRole("region", { name: /^Hosts/ });
  expect(await within(hosts).findByRole("alert")).toBeTruthy();
  expect(document.querySelectorAll("[data-gpu]").length).toBe(0);
  expect(screen.getByRole("region", { name: /^Recent runs/ })).toBeTruthy();
  view.unmount();
  mockApi({ "GET /api/v1/hosts": makeHosts() });
  renderWithClient(<HomePage />);
  expect((await screen.findByRole("alert")).textContent).toBe("unmocked GET /api/v1/overview");
});
