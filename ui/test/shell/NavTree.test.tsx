import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterContextProvider, createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { RunRecord, TaskSummary } from "../../src/api/models";
import { createAppRouter } from "../../src/router";
import { NavTree, buildTree, isTaskPath } from "../../src/shell/NavTree";
import { mockApi, restoreFetch } from "../pages/helpers";

afterEach(restoreFetch);

const task = (project: string, name: string, n_runs: number) => ({ project, name, n_runs }) as TaskSummary;
const live = (project: string, t: string, status: "running" | "queued") => ({ project, task: t, status }) as RunRecord;

const TASKS = [task("rxn-forward", "uspto-forward-top1", 39), task("retro agent", "bench/200", 27), task("rxn-forward", "aaa", 0)];
const RUNNING = [live("rxn-forward", "uspto-forward-top1", "running"), live("rxn-forward", "uspto-forward-top1", "running"), live("rxn-forward", "uspto-forward-top1", "queued")];

async function renderNav(path: string, routes: Record<string, unknown>) {
  mockApi(routes);
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  await router.load();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RouterContextProvider router={router}>
        <NavTree />
      </RouterContextProvider>
    </QueryClientProvider>,
  );
}

describe("buildTree", () => {
  test("projects and tasks by name, run counts, running runs only", () => {
    expect(buildTree(TASKS, RUNNING)).toEqual([
      { project: "retro agent", tasks: [{ task: "bench/200", runs: 27, running: 0 }] },
      {
        project: "rxn-forward",
        tasks: [
          { task: "aaa", runs: 0, running: 0 },
          { task: "uspto-forward-top1", runs: 39, running: 2 },
        ],
      },
    ]);
    expect(buildTree([], [])).toEqual([]);
  });

  test("isTaskPath matches the task page and its sub-pages, encoded or not", () => {
    expect([
      isTaskPath("/t/retro%20agent/bench%2F200", "retro agent", "bench/200"),
      isTaskPath("/t/rxn-forward/aaa/edit/new", "rxn-forward", "aaa"),
      isTaskPath("/t/rxn-forward/aaab", "rxn-forward", "aaa"),
      isTaskPath("/r/x", "rxn-forward", "aaa"),
    ]).toEqual([true, true, false, false]);
  });
});

describe("NavTree", () => {
  const routes = {
    "GET /api/v1/tasks": TASKS,
    "GET /api/v1/overview": { counts: { queued: 3 }, running: RUNNING },
    "GET /api/v1/hosts": ["local", "gpu1", "cluster"].map((name) => ({ name, gpus: [], queue: 0, state: { state: "connected" } })),
  };

  test("Home, Hosts and Queue with their counts; Home is current on /", async () => {
    await renderNav("/", routes);
    const nav = screen.getByRole("navigation", { name: "Navigation" });
    const home = within(nav).getByRole("link", { name: "Home" });
    expect([home.getAttribute("href"), home.getAttribute("aria-current")]).toEqual(["/", "page"]);
    await waitFor(() => expect(within(nav).getByRole("link", { name: /Hosts/ }).textContent).toBe("Hosts3"));
    await waitFor(() => expect(within(nav).getByRole("link", { name: /Queue/ }).textContent).toBe("Queue3"));
  });

  test("projects with avatars, tasks with run counts, a spinner where runs are running", async () => {
    await renderNav("/t/retro%20agent/bench%2F200", routes);
    const link = await screen.findByRole("link", { name: /uspto-forward-top1/ });
    expect(link.getAttribute("href")).toBe("/t/rxn-forward/uspto-forward-top1");
    expect(link.querySelector(".count")?.textContent).toBe("39");
    expect(link.querySelector(".st.running")?.getAttribute("title")).toBe("2 running");
    const encoded = screen.getByRole("link", { name: /bench\/200/ });
    expect(encoded.getAttribute("href")).toBe("/t/retro%20agent/bench%2F200");
    expect(encoded.getAttribute("aria-current")).toBe("page");
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(encoded.querySelector(".st")).toBeNull();
    expect([...document.querySelectorAll(".item.proj")].map((p) => p.textContent)).toEqual(["RAretro agent", "RFrxn-forward"]);
  });

  test("a fresh install says there are no projects yet", async () => {
    await renderNav("/", { "GET /api/v1/tasks": [], "GET /api/v1/overview": { counts: {}, running: [] }, "GET /api/v1/hosts": [] });
    expect(await screen.findByText("No projects yet")).not.toBeNull();
  });
});
