import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";

import type { ProjectInfo, RunRecord, TaskSummary } from "../../src/api/models";
import { type CommandHandlers, MAX_RUNS, buildCommands, filterCommands } from "../../src/shell/CommandPalette";
import { mockRoutes } from "../api/fetch-mock";
import { renderApp } from "../render-app";

function makeRun(over: Partial<RunRecord> & { run_id: string }): RunRecord {
  return {
    project: "toy",
    task: "acc",
    hypothesis: "",
    kind: "full",
    parent: null,
    stage: null,
    command: ["python", "train.py"],
    command_template: ["python", "train.py"],
    vars: {},
    params: {},
    cwd: "/Users/me/toy",
    environment_id: "env1",
    host: "mac",
    executor: { type: "local", pid: null, pid_create_time: null, child_pid: null },
    git: { repo: null, commit: null, branch: null, dirty: false, untracked_count: 0, untracked: [] },
    datasets: [],
    seed: null,
    config_hash: "sha256:abc",
    status: "finished",
    created_at: "2026-09-27T10:00:00Z",
    started_at: null,
    ended_at: null,
    exit_code: null,
    artifacts: [],
    tags: [],
    starred: false,
    archived: false,
    created_by: "human",
    usage: null,
    ...over,
  };
}

const dataset = (name: string, path: string, host = "local") => ({
  name, version: "v1", split: "test", host, path, hash: null, hash_mode: null, size: null, checked_at: null,
});

const PROJECTS: ProjectInfo[] = [{ project: "toy", repo: "/Users/me/toy", description: "", tasks: ["acc", "f1"] }];
const TASKS: TaskSummary[] = [
  { project: "toy", name: "acc", description: "accuracy on the toy set", dataset: "toy", dataset_version: "v1",
    split: "test", metrics: { accuracy: "v1" }, primary: "accuracy", higher_is_better: true, n_runs: 6, best: 0.9 },
  { project: "toy", name: "f1", description: "", dataset: "toy", dataset_version: "v1",
    split: "test", metrics: { f1: "v1" }, primary: "f1", higher_is_better: true, n_runs: 1, best: null },
];
const RUNS: RunRecord[] = [
  makeRun({ run_id: "r-svm", hypothesis: "RBF-kernel SVM beats rf", seed: 1, tags: ["baseline"],
    datasets: [dataset("toy", "/data/test.jsonl")] }),
  makeRun({ run_id: "r-old", hypothesis: "debug test", archived: true }),
  makeRun({ run_id: "r-gpu", hypothesis: "", status: "running", cwd: "/scratch/wt",
    datasets: [dataset("big", "/scratch/train.jsonl", "gpu1"), dataset("toy", "/data/test.jsonl")] }),
];

function handlers(): CommandHandlers & { calls: unknown[] } {
  const calls: unknown[] = [];
  return {
    calls,
    go: (t) => calls.push(["go", t]),
    copy: (p) => calls.push(["copy", p]),
    toggleTheme: () => calls.push(["theme"]),
  };
}

describe("buildCommands", () => {
  test("lists go-to, tasks, unarchived runs, paths and commands in order", () => {
    const items = buildCommands({ projects: PROJECTS, tasks: TASKS, runs: RUNS }, handlers());
    expect(items.map((c) => [c.group, c.title, c.subtitle])).toEqual([
      ["Go to", "Overview", "all projects"],
      ["Tasks", "toy / acc", "6 runs"],
      ["Tasks", "toy / f1", "1 run"],
      ["Runs", "r-svm", "RBF-kernel SVM beats rf, seed 1, finished"],
      ["Runs", "r-gpu", "acc, running"],
      ["Paths", "Copy toy repo", "/Users/me/toy"],
      ["Paths", "Copy toy data", "/data/test.jsonl"],
      ["Paths", "Copy big data", "gpu1:/scratch/train.jsonl"],
      ["Commands", "Switch colour mode", "light or dark"],
    ]);
  });

  test("items call the matching handler", () => {
    const h = handlers();
    const items = buildCommands({ projects: PROJECTS, tasks: TASKS, runs: RUNS }, h);
    for (const title of ["toy / acc", "r-gpu", "Copy big data", "Switch colour mode"]) {
      items.find((c) => c.title === title)?.run();
    }
    expect(h.calls).toEqual([
      ["go", { to: "/t/$project/$task", params: { project: "toy", task: "acc" } }],
      ["go", { to: "/r/$runId", params: { runId: "r-gpu" } }],
      ["copy", "gpu1:/scratch/train.jsonl"],
      ["theme"],
    ]);
  });
});

describe("buildCommands edge cases", () => {
  test("an empty store still offers Overview and the colour switch", () => {
    const items = buildCommands({ projects: [], tasks: [], runs: [] }, handlers());
    expect(items.map((c) => c.title)).toEqual(["Overview", "Switch colour mode"]);
  });

  test(`lists at most ${MAX_RUNS} runs`, () => {
    const many = Array.from({ length: 60 }, (_, i) => makeRun({ run_id: `r-${i}` }));
    const items = buildCommands({ projects: [], tasks: [], runs: many }, handlers());
    expect(items.filter((c) => c.group === "Runs")).toHaveLength(MAX_RUNS);
  });
});

describe("filterCommands", () => {
  const items = buildCommands({ projects: PROJECTS, tasks: TASKS, runs: RUNS }, handlers());
  const titles = (q: string) => filterCommands(items, q).map((c) => c.title);

  test("an empty query keeps everything", () => {
    expect(titles("  ")).toHaveLength(items.length);
  });

  test("matches hypothesis and tags case-insensitively", () => {
    expect(titles("SVM")).toEqual(["r-svm"]);
    expect(titles("baseline")).toEqual(["r-svm"]);
  });

  test("every word must match; paths are searchable", () => {
    expect(titles("gpu1 train")).toEqual(["Copy big data"]);
    expect(titles("/users/me/toy")).toEqual(["r-svm", "Copy toy repo"]);
    expect(titles("svm running")).toEqual([]);
  });
});

describe("CommandPalette", () => {
  const realFetch = globalThis.fetch;
  let writeText: ReturnType<typeof mock>;

  beforeEach(() => {
    // "/api/v1/tasks/" answers 404 so the Task page opened by Enter shows its error box
    // instead of reading the task list as a leaderboard.
    mockRoutes({ "/api/v1/projects": PROJECTS, "/api/v1/tasks": TASKS, "/api/v1/tasks/": null, "/api/v1/runs": RUNS });
    writeText = mock(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  const openWithShortcut = async () => {
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    return screen.findByRole("dialog", { name: "Find and run commands" });
  };

  test("Ctrl+K opens it with the input focused; Escape closes and refocuses Find", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    const dialog = await openWithShortcut();
    const input = screen.getByPlaceholderText("Find a run, task, path or command");
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement?.id).toBe("findBtn");
  });

  test("the input is a named combobox for the list, and Tab stays inside the dialog", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    const dialog = await openWithShortcut();
    const input = screen.getByRole("combobox", { name: "Find a run, task, path or command" });
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(input.getAttribute("aria-controls")).toBe(screen.getByRole("listbox").id);
    expect(input.getAttribute("aria-autocomplete")).toBe("list");
    expect(fireEvent.keyDown(input, { key: "Tab" })).toBe(false);
    expect(fireEvent.keyDown(input, { key: "Tab", shiftKey: true })).toBe(false);
    // Focus lost (a click on the box) comes back to the input on Tab.
    input.blur();
    expect(document.activeElement).not.toBe(input);
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(input);
    expect(screen.getByRole("dialog")).toBe(dialog);
  });

  test("typing filters, Enter opens the selected task", async () => {
    const { router } = renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    fireEvent.click(screen.getByRole("button", { name: /Find a run, task or path/ }));
    await screen.findByRole("option", { name: /toy \/ acc/ });
    const input = screen.getByPlaceholderText("Find a run, task, path or command");
    fireEvent.change(input, { target: { value: "acc" } });
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.querySelector("span")?.textContent)).toEqual(["toy / acc", "r-svm", "r-gpu"]);
    expect(options[0]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/t/toy/acc"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("arrow keys move the selection and stop at the ends", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    const dialog = await openWithShortcut();
    await screen.findByRole("option", { name: /r-gpu/ });
    fireEvent.change(screen.getByPlaceholderText(/Find a run/), { target: { value: "copy" } });
    const selected = () => screen.getAllByRole("option").findIndex((o) => o.getAttribute("aria-selected") === "true");
    fireEvent.keyDown(dialog, { key: "ArrowUp" });
    expect(selected()).toBe(0);
    for (let i = 0; i < 5; i++) fireEvent.keyDown(dialog, { key: "ArrowDown" });
    expect(selected()).toBe(2);
  });

  test("a path item copies and shows a toast", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    fireEvent.click(await screen.findByRole("option", { name: /Copy toy repo/ }));
    expect(writeText).toHaveBeenCalledWith("/Users/me/toy");
    expect(screen.getByRole("status").textContent).toBe("Copied /Users/me/toy");
  });

  test("the colour mode command toggles the theme", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    await act(async () => {
      fireEvent.click(screen.getByRole("option", { name: /Switch colour mode/ }));
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch colour mode" }).textContent).toBe("Light");
  });

  test("with the API failing it still offers Overview and the colour switch", async () => {
    mockRoutes({});
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    await waitFor(() => expect(screen.queryByText("Loading…")).toBeNull());
    expect(screen.getAllByRole("option").map((o) => o.querySelector("span")?.textContent)).toEqual([
      "Overview",
      "Switch colour mode",
    ]);
  });

  test("shows Nothing matches for a query with no hits", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    await screen.findByRole("option", { name: /r-svm/ });
    fireEvent.change(screen.getByPlaceholderText(/Find a run/), { target: { value: "zzzz" } });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("Nothing matches")).toBeTruthy();
  });
});

test("run params are searchable and owned sweeps are unique per project", () => {
  const h = handlers();
  const run = makeRun({ run_id: "p1", params: { lr: "0.1" }, sweep_id: "s-one", tags: ["sweep:abcdefgh:s-one"] });
  const data = { projects: [], tasks: [], hubEnvironmentId: "abcdefgh-rest", runs: [run, { ...run, run_id: "p2" }, { ...run, run_id: "p3", project: "other" }, { ...run, run_id: "foreign", tags: ["sweep:zzzzzzzz:s-one"] }] };
  const items = buildCommands(data, h);
  expect(filterCommands(items, "lr=0.1").filter((i) => i.group === "Runs")).toHaveLength(4);
  expect(items.filter((i) => i.group === "Sweeps")).toHaveLength(2);
  items.find((i) => i.group === "Sweeps")?.run();
  expect(h.calls[0]).toEqual(["go", { to: "/s/$project/$id", params: { project: "toy", id: "s-one" } }]);
  expect(buildCommands({ ...data, hubEnvironmentId: null }, h).some((i) => i.group === "Sweeps")).toBe(false);
});
