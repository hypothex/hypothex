import { afterEach, describe, expect, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { NAV_KEY } from "../../src/shell/AppShell";
import { crumbsFor, paletteShortcut } from "../../src/shell/TopBar";
import { mockRoutes } from "../api/fetch-mock";
import { RUN_SVM, makeBoard, makeDetail } from "../pages/fixtures";
import { renderApp } from "../render-app";
import { makeTaskRuns } from "../run/taskRunsFixtures";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const PROJECTS = [{ project: "toy", repo: "/home/me/toy", description: "", tasks: ["acc"] }];

describe("crumbsFor", () => {
  test("one crumb trail per screen; the task crumb links to the task", () => {
    expect(crumbsFor("/")).toEqual([{ label: "Home" }]);
    expect(crumbsFor("/t/retro%20agent/bench%2F200")).toEqual([
      { label: "retro agent" },
      { label: "bench/200", href: "/t/retro%20agent/bench%2F200" },
    ]);
    expect(crumbsFor("/t/toy/acc/edit/new").at(-1)).toEqual({ label: "new view" });
    expect(crumbsFor("/t/toy/acc/edit/route").at(-1)).toEqual({ label: "edit route" });
    expect(crumbsFor("/r/20261015-145600-uspto-2d2f")).toEqual([{ label: "2d2f" }]);
    expect(crumbsFor("/r/x", { project: "toy", task: "acc", name: "warm restart" })).toEqual([
      { label: "toy" },
      { label: "acc", href: "/t/toy/acc" },
      { label: "warm restart" },
    ]);
    expect(crumbsFor("/r/x", { project: "toy", task: null, name: "x" })).toEqual([{ label: "toy" }, { label: "x" }]);
    expect(crumbsFor("/x/20261015-a-1111/20261015-b-2222")).toEqual([{ label: "Examples" }, { label: "1111 vs 2222" }]);
    expect(crumbsFor("/s/rxn/s-7f3a")).toEqual([{ label: "rxn" }, { label: "sweep s-7f3a" }]);
    expect([crumbsFor("/hosts"), crumbsFor("/queue"), crumbsFor("/nope")]).toEqual([
      [{ label: "Hosts" }],
      [{ label: "Queue" }],
      [{ label: "Not found" }],
    ]);
  });

  test("paletteShortcut shows the platform's modifier", () => {
    expect([paletteShortcut("MacIntel"), paletteShortcut("Win32")]).toEqual(["⌘K", "Ctrl K"]);
  });
});

describe("AppShell", () => {
  test("nav, breadcrumb, search, live and New run frame every page", async () => {
    mockRoutes({ "/.well-known/hypothex/environment": { hx_version: "0.5.0" } });
    renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Navigation" });
    expect(within(nav).getByRole("link", { name: "Home" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Hypothex, home" }).getAttribute("href")).toBe("/");
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("navigation", { name: "Breadcrumb" }).textContent).toBe("Home");
    expect(within(bar).getByRole("status", { name: "Live updates on" }).textContent).toBe("live");
    expect(within(bar).getByRole("button", { name: /Search runs, tasks, paths/ }).id).toBe("findBtn");
    expect(await screen.findByText("hub · v0.5.0")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Switch colour mode" })).not.toBeNull();
  });

  test("the run crumb is the run's display name: derived name with seed, else from the hypothesis", async () => {
    const { cleanup } = await import("@testing-library/react");
    const runRoutes = { [`/api/v1/runs/${RUN_SVM}`]: makeDetail() };
    const page = () => screen.getByRole("navigation", { name: "Breadcrumb" }).querySelector('[aria-current="page"]');
    mockRoutes({ ...runRoutes, "/api/v1/tasks/toy-classifier/toy-test/runs": makeTaskRuns() });
    renderApp(`/r/${RUN_SVM}`);
    await waitFor(() => expect(page()?.textContent).toBe("model svm · seed 3"));
    cleanup();
    mockRoutes(runRoutes);
    renderApp(`/r/${RUN_SVM}`);
    await waitFor(() => expect(page()?.textContent).toBe("RBF-kernel SVM · seed 3"));
  });

  test("the live indicator says when updates are off or reconnecting", async () => {
    mockRoutes({});
    const { cleanup } = await import("@testing-library/react");
    renderApp("/", { streamStatus: "offline" });
    const off = await screen.findByRole("status", { name: "Live updates off" });
    expect([off.textContent, off.getAttribute("title")]).toEqual(["offline", "Live updates are off: data is not live, reload to reconnect"]);
    cleanup();
    renderApp("/", { streamStatus: "connected" });
    expect((await screen.findByRole("status", { name: "Live updates reconnecting" })).textContent).toBe("connecting");
  });

  test("the search button opens the command palette", async () => {
    mockRoutes({});
    renderApp("/");
    fireEvent.click(await screen.findByRole("button", { name: /Search runs, tasks, paths/ }));
    expect(await screen.findByRole("dialog", { name: "Find and run commands" })).not.toBeNull();
  });

  test("Ctrl+. hides and shows the nav, and remembers it", async () => {
    mockRoutes({});
    renderApp("/");
    await screen.findByRole("navigation", { name: "Navigation" });
    fireEvent.keyDown(document, { key: ".", ctrlKey: true });
    expect(screen.queryByRole("navigation", { name: "Navigation" })).toBeNull();
    expect(localStorage.getItem(NAV_KEY)).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "Show navigation" }));
    expect(screen.getByRole("navigation", { name: "Navigation" })).not.toBeNull();
    expect(localStorage.getItem(NAV_KEY)).toBe("1");
  });

  test("New run waits for a project, then opens the Launch dialog; on a task it waits for the leaderboard", async () => {
    mockRoutes({});
    const { cleanup } = await import("@testing-library/react");
    renderApp("/");
    const disabled = within(await screen.findByRole("banner")).getByRole("button", { name: "New run" });
    expect([disabled.hasAttribute("disabled"), disabled.getAttribute("title")]).toEqual([true, "No project yet: run hx init"]);
    cleanup();
    mockRoutes({ "/api/v1/projects": PROJECTS });
    renderApp("/hosts");
    const button = within(await screen.findByRole("banner")).getByRole("button", { name: "New run" });
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
    expect(button.getAttribute("title")).toBe("New run in toy");
    fireEvent.click(button);
    expect(await screen.findByRole("dialog", { name: "New run" })).not.toBeNull();
    cleanup();
    // the task page's own header is a second banner to Testing Library: use the top bar
    mockRoutes({ "/api/v1/projects": PROJECTS, "/api/v1/tasks/toy/acc/leaderboard": makeBoard() });
    renderApp("/t/toy/acc");
    const top = await waitFor(() => {
      const el = document.querySelector<HTMLElement>("header.top");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    const onTask = within(top).getByRole("button", { name: "New run" });
    await waitFor(() => expect(onTask.hasAttribute("disabled")).toBe(false));
    expect(onTask.getAttribute("title")).toBe("New run in toy / acc, from the best config");
    fireEvent.click(onTask);
    expect(await screen.findByRole("dialog", { name: "New run" })).not.toBeNull();
  });
});
