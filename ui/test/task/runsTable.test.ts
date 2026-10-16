import { expect, test } from "bun:test";
import { fmtP } from "../../src/pages/components/format";
import { columnsKey, identityCells, loadHiddenColumns, runCells, runsColumns, saveHiddenColumns, sortItems } from "../../src/task/runsTable";
import { listIdentities, parseSelection } from "../../src/task/useRunSelection";
import { PROJECT, TASK, makeTaskRuns } from "./fixtures";

const sel = parseSelection(new URLSearchParams(), { sortDir: "desc" });
const data = makeTaskRuns();
const items = listIdentities(sel, data);
const byId = (id: string) => items.find((i) => i.id === id) ?? (() => { throw new Error(id); })();

test("columns: status, each varying param, the primary, CI, Δ best, run facts", () => {
  expect(runsColumns(data).map((c) => c.label)).toEqual(["Status", "lr", "beam", "top1", "95% CI", "Δ best", "Launcher", "Host", "GPU-h", "Started", "Commit", "Tags"]);
});

test("config cells: counts per status, mean ± sd, test interval, Δ best muted inside noise", () => {
  const a = identityCells(byId("g-a"), data);
  expect(a).toMatchObject({ status: [["finished", 2], ["running", 1]], params: { lr: "3e-4", beam: "10" }, mean: 0.911, sd: 0.0014, ci: { lo: 0.905, hi: 0.917 }, delta: null, host: ["gpu1"], gpu: 3, started: "2026-10-03T09:00:05Z", commit: ["8f4cac4"], tags: ["final"] });
  const b = identityCells(byId("g-b"), data);
  expect(b.delta).toBeCloseTo(-0.013, 10);
  expect(b.deltaMuted).toBe(false);
  expect(b.deltaTitle).toBe(`outside the best config's interval · ${fmtP(0.01)}`);
  const c = identityCells(byId("g-c"), data);
  expect(c).toMatchObject({ status: [["queued", 1], ["failed", 1]], mean: null, delta: null, ci: null, gpu: 1.5 });
  const d = identityCells(listIdentities({ ...sel, showSuperseded: true }, data).find((i) => i.id === "g-d") ?? byId("g-a"), data);
  expect(d.deltaMuted).toBe(true);
});

test("a seed row: its own value and status, Δ against the best config", () => {
  const run = data.runs.find((r) => r.run_id === "run-b1");
  if (!run) throw new Error("fixture");
  const cells = runCells(run, data.groups.find((g) => g.group_id === "g-b") ?? null, data);
  expect(cells).toMatchObject({ status: [["finished", 1]], mean: 0.899, sd: null, ci: null, host: ["dgx"] });
  expect(cells.delta).toBeCloseTo(-0.012, 10);
});

test("sort by a column; missing values last; null column keeps the list order", () => {
  expect(sortItems(items, data, "param:host", "desc").map((i) => i.id)).toEqual(["g-a", "g-b", "g-c"]);
  expect(sortItems(items, data, "host", "desc").map((i) => i.id)).toEqual(["g-a", "g-c", "g-b"]);
  expect(sortItems(items, data, "host", "asc").map((i) => i.id)).toEqual(["g-b", "g-a", "g-c"]);
  expect(sortItems(items, data, "primary", "asc").map((i) => i.id)).toEqual(["g-b", "g-a", "g-c"]);
  expect(sortItems(items, data, "param:lr", "asc").map((i) => i.id)).toEqual(["g-b", "g-a", "g-c"]);
  expect(sortItems(items, data, null, "asc").map((i) => i.id)).toEqual(["g-a", "g-b", "g-c"]);
});

test("hidden columns persist per task and survive bad storage", () => {
  saveHiddenColumns(PROJECT, TASK, ["host", "tags"]);
  expect(loadHiddenColumns(PROJECT, TASK)).toEqual(["host", "tags"]);
  localStorage.setItem(columnsKey(PROJECT, TASK), "{not json");
  expect(loadHiddenColumns(PROJECT, TASK)).toEqual([]);
});
