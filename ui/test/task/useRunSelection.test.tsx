import { beforeEach, describe, expect, test } from "bun:test";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import {
  type Selection,
  defaultSelection,
  keyLabel,
  listIdentities,
  parseSelection,
  runLabel,
  selectionSearch,
  useRunSelection,
  visibleIdentities,
} from "../../src/task/useRunSelection";
import { type SetSearch, applySearch, useSearchState } from "../../src/task/useSearchState";
import { makeTaskRun, makeTaskRuns } from "./fixtures";

const DEFAULTS = { sortDir: "desc" as const };
const base = (over: Partial<Selection> = {}): Selection => ({ ...parseSelection(new URLSearchParams(), DEFAULTS), ...over });

beforeEach(() => window.history.replaceState(null, "", "/t/toy-proj/toy-task"));

describe("URL state", () => {
  test("no keys: every default", () => {
    expect(parseSelection(new URLSearchParams(), DEFAULTS)).toEqual({
      filter: "",
      group: "config",
      sort: { key: "primary", dir: "desc" },
      hidden: [],
      showSuperseded: false,
      column: "primary",
    });
  });

  test("defaultSelection sorts best first for either direction", () => {
    expect(defaultSelection(true).sort).toEqual({ key: "primary", dir: "desc" });
    expect(defaultSelection(false)).toEqual({ ...base(), sort: { key: "primary", dir: "asc" } });
  });

  test("reads filter, group, sort, hide, sup and col", () => {
    const params = new URLSearchParams("filter=lr%3D3e-4&group=run&sort=created:asc&hide=g-a,g-b&sup=1&col=top1/final");
    expect(parseSelection(params, DEFAULTS)).toEqual({
      filter: "lr=3e-4",
      group: "run",
      sort: { key: "created", dir: "asc" },
      hidden: ["g-a", "g-b"],
      showSuperseded: true,
      column: "top1/final",
    });
  });

  test("a sort key may hold colons; a bad direction falls back to the default sort", () => {
    expect(parseSelection(new URLSearchParams("sort=reported/a:b.top10:asc"), DEFAULTS).sort).toEqual({
      key: "reported/a:b.top10",
      dir: "asc",
    });
    expect(parseSelection(new URLSearchParams("sort=created:up"), { sortDir: "asc" }).sort).toEqual({
      key: "primary",
      dir: "asc",
    });
  });

  test("defaults are written as removals, duplicates in hide collapse", () => {
    expect(
      selectionSearch(
        { filter: "  ", group: "config", sort: { key: "primary", dir: "desc" }, hidden: [], showSuperseded: false, column: "primary" },
        DEFAULTS,
      ),
    ).toEqual({ filter: null, group: null, sort: null, hide: null, sup: null, col: null });
    expect(
      selectionSearch(
        { group: "run", hidden: ["g-a", "g-a", "g-b"], showSuperseded: true, sort: { key: "primary", dir: "asc" }, column: "top1/final" },
        DEFAULTS,
      ),
    ).toEqual({ group: "run", hide: "g-a,g-b", sup: "1", sort: "primary:asc", col: "top1/final" });
  });

  test("applySearch patches one key and keeps the others", () => {
    expect(applySearch("?tab=runs&filter=x", { filter: null, group: "run" })).toBe("?tab=runs&group=run");
    expect(applySearch("", { filter: "" })).toBe("");
  });

  test("useRunSelection reads the page URL and writes patches back to it", () => {
    window.history.replaceState(null, "", "/t/toy-proj/toy-task?tab=runs&filter=beam");
    let patch: (p: Partial<Selection>) => void = () => {};
    function Probe() {
      const [sel, set] = useRunSelection();
      patch = set;
      return <output>{`${sel.filter}|${sel.group}|${sel.hidden.join(",")}`}</output>;
    }
    render(<Probe />);
    expect(screen.getByRole("status").textContent).toBe("beam|config|");
    act(() => patch({ group: "run", hidden: ["run-a1"] }));
    expect(screen.getByRole("status").textContent).toBe("beam|run|run-a1");
    expect(window.location.search).toBe("?tab=runs&filter=beam&group=run&hide=run-a1");
  });

  test("under a router, useSearchState reads and writes the router's history", async () => {
    let setSearch: SetSearch = () => {};
    function Probe() {
      const [params, set] = useSearchState();
      setSearch = set;
      return <output>{params.toString()}</output>;
    }
    const history = createMemoryHistory({ initialEntries: ["/t/toy-proj/toy-task?tab=runs"] });
    const router = createRouter({ routeTree: createRootRoute({ component: Probe }), history });
    await act(async () => {
      render(<RouterProvider router={router} />);
    });
    expect(screen.getByRole("status").textContent).toBe("tab=runs");
    const length = history.length;
    await act(async () => setSearch({ filter: "beam" }));
    expect(screen.getByRole("status").textContent).toBe("tab=runs&filter=beam");
    expect(history.location.search).toBe("?tab=runs&filter=beam");
    expect(history.length).toBe(length);
    await act(async () => setSearch({ tab: "charts" }, { push: true }));
    expect(history.location.search).toBe("?tab=charts&filter=beam");
    expect(history.length).toBe(length + 1);
    expect(window.location.search).toBe("");
  });
});

describe("identities", () => {
  test("by config: best first, unscored last, superseded hidden until shown", () => {
    const items = listIdentities(base(), makeTaskRuns());
    expect(items.map((i) => i.id)).toEqual(["g-a", "g-b", "g-c"]);
    expect(items[0]).toMatchObject({ kind: "group", name: "lr 3e-4 · beam 10", value: 0.911, sd: 0.0014, hidden: false });
    expect(items[0]?.runs.map((r) => r.run_id)).toEqual(["run-a1", "run-a2", "run-a3"]);
    expect(listIdentities(base({ showSuperseded: true }), makeTaskRuns()).map((i) => i.id)).toEqual([
      "g-a",
      "g-d",
      "g-b",
      "g-c",
    ]);
  });

  test("ascending primary for a lower-is-better default", () => {
    const sel = parseSelection(new URLSearchParams(), { sortDir: "asc" });
    expect(listIdentities(sel, makeTaskRuns()).map((i) => i.id)).toEqual(["g-b", "g-a", "g-c"]);
  });

  test("each run: run ids, seed in the label not in the base name, unscored newest first", () => {
    const items = listIdentities(base({ group: "run" }), makeTaskRuns());
    expect(items.map((i) => i.id)).toEqual(["run-a1", "run-a2", "run-b1", "run-b2", "run-c2", "run-a3", "run-c1"]);
    expect(items[0]?.name).toBe("lr 3e-4 · beam 10 · seed 1");
    expect(items[0]?.baseName).toBe("lr 3e-4 · beam 10");
  });

  test("a renamed run shows its own name with no seed", () => {
    expect(runLabel(makeTaskRun({ name: "svm, tuned C", renamed: true, seed: 2 }))).toBe("svm, tuned C");
    expect(runLabel(makeTaskRun({ name: "stale", renamed: false, seed: null }))).toBe("lr 3e-4 · beam 10");
  });

  test("runs the server lists in no group still get one identity per group id", () => {
    const data = makeTaskRuns();
    const items = listIdentities(base(), { ...data, groups: data.groups.filter((g) => g.group_id !== "g-b") });
    expect(items.map((i) => [i.id, i.runs.length, i.value])).toEqual([
      ["g-a", 3, 0.911],
      ["g-c", 2, null],
      ["g-b", 2, null],
    ]);
  });

  test("sort by another score key, by created, and by a key that no longer exists", () => {
    const data = makeTaskRuns();
    expect(listIdentities(base({ sort: { key: "top1/final", dir: "asc" } }), data).map((i) => i.id)).toEqual(["g-b", "g-a", "g-c"]);
    expect(listIdentities(base({ sort: { key: "created", dir: "desc" } }), data).map((i) => i.id)).toEqual(["g-c", "g-a", "g-b"]);
    // every value is missing: newest first
    expect(listIdentities(base({ sort: { key: "gone/key", dir: "desc" } }), data).map((i) => i.id)).toEqual(["g-c", "g-a", "g-b"]);
  });

  test("a group is listed when any run matches the filter; hidden ids stay listed, not visible", () => {
    const data = makeTaskRuns();
    expect(listIdentities(base({ filter: "status:queued", hidden: ["g-a"] }), data).map((i) => [i.id, i.hidden])).toEqual([
      ["g-c", false],
    ]);
    const sel = base({ hidden: ["g-b", "gone-id"] });
    expect(visibleIdentities(sel, data)).toEqual(["g-a", "g-c"]);
    expect(listIdentities(sel, data).find((i) => i.id === "g-b")?.hidden).toBe(true);
  });

  test("keyLabel shortens score keys", () => {
    expect(keyLabel("top1/value")).toBe("top1");
    expect(keyLabel("reported/test-a.model-x.top10")).toBe("test-a.model-x.top10");
    expect(keyLabel("loss")).toBe("loss");
  });
});
