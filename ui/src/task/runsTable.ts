/**
 * The Runs tab table (spec 4.2 "Runs"): columns, the cells of a config or a run, sorting,
 * and the column chooser's stored choice (localStorage, per task).
 */
import type { RunStatus, TaskGroup, TaskRun, TaskRuns } from "../api/models";
import { fmtP } from "../pages/components/format";
import { type Identity, keyLabel } from "./useRunSelection";

export interface RunsColumn {
  id: string;
  label: string;
  numeric: boolean;
}

export function runsColumns(data: TaskRuns): RunsColumn[] {
  return [
    { id: "status", label: "Status", numeric: false },
    ...data.varying_keys.map((k) => ({ id: `param:${k}`, label: k, numeric: false })),
    { id: "primary", label: keyLabel(data.primary), numeric: true },
    { id: "ci", label: "95% CI", numeric: true },
    { id: "delta", label: "Δ best", numeric: true },
    { id: "launcher", label: "Launcher", numeric: false },
    { id: "host", label: "Host", numeric: false },
    { id: "gpu", label: "GPU-h", numeric: true },
    { id: "started", label: "Started", numeric: false },
    { id: "commit", label: "Commit", numeric: false },
    { id: "tags", label: "Tags", numeric: false },
  ];
}

export const STATUS_ORDER: readonly RunStatus[] = ["finished", "running", "queued", "failed", "killed", "lost"];

export interface Cells {
  status: [RunStatus, number][];
  params: Record<string, string>;
  mean: number | null;
  sd: number | null;
  ci: { lo: number; hi: number } | null;
  delta: number | null;
  deltaMuted: boolean;
  deltaTitle: string | undefined;
  launcher: string[];
  host: string[];
  gpu: number | null;
  started: string | null;
  commit: string[];
  tags: string[];
}

export function bestGroup(data: TaskRuns): TaskGroup | undefined {
  return data.groups.find((g) => g.is_best && g.primary !== null);
}

const uniq = (values: readonly (string | null | undefined)[]): string[] =>
  [...new Set(values.filter((v): v is string => typeof v === "string" && v !== ""))];

export function cellsFor(
  runs: readonly TaskRun[],
  group: TaskGroup | null,
  value: number | null,
  sd: number | null,
  data: TaskRuns,
  asGroup: boolean,
): Cells {
  const best = bestGroup(data);
  const isBest = asGroup && best !== undefined && group?.group_id === best.group_id;
  const delta = best?.primary && value !== null && !isBest ? value - best.primary.mean : null;
  const within = group?.within_noise_of_best === true;
  const p = group?.vs_best?.p;
  const hours = runs.map((r) => r.gpu_hours).filter((h): h is number => typeof h === "number" && Number.isFinite(h));
  return {
    status: STATUS_ORDER.map((s): [RunStatus, number] => [s, runs.filter((r) => r.status === s).length]).filter(([, n]) => n > 0),
    params: Object.fromEntries(data.varying_keys.map((k) => [k, uniq(runs.map((r) => r.params[k])).join(", ")])),
    mean: value,
    sd,
    ci: asGroup && group?.test_interval ? { lo: group.test_interval.lo, hi: group.test_interval.hi } : null,
    delta,
    deltaMuted: delta !== null && within,
    deltaTitle:
      delta === null ? undefined : `${within ? "inside" : "outside"} the best config's interval${typeof p === "number" ? ` · ${fmtP(p)}` : ""}`,
    launcher: uniq(runs.map((r) => r.created_by)),
    host: uniq(runs.map((r) => r.host)),
    gpu: hours.length ? hours.reduce((a, b) => a + b, 0) : null,
    started: runs.map((r) => r.started_at).filter((s): s is string => typeof s === "string").sort()[0] ?? null,
    commit: uniq(runs.map((r) => r.commit?.slice(0, 7))),
    tags: uniq(runs.flatMap((r) => r.tags)),
  };
}

export function identityCells(item: Identity, data: TaskRuns): Cells {
  return cellsFor(item.runs, item.group, item.value, item.sd, data, item.kind === "group");
}

export function runCells(run: TaskRun, group: TaskGroup | null, data: TaskRuns): Cells {
  return cellsFor([run], group, run.primary, null, data, false);
}

export type TableSortDir = "asc" | "desc";

const NUMERIC = /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i;

function sortValue(item: Identity, cells: Cells, col: string): number | string | null {
  if (col === "name") return item.name.toLowerCase();
  if (col.startsWith("param:")) {
    const v = cells.params[col.slice(6)] ?? "";
    if (v === "") return null;
    return NUMERIC.test(v) ? Number(v) : v;
  }
  const joined = (list: readonly string[]): string | null => (list.length ? list.join(", ") : null);
  switch (col) {
    case "status":
      return joined(cells.status.map(([s]) => s));
    case "primary":
      return cells.mean;
    case "ci":
      return cells.ci?.lo ?? null;
    case "delta":
      return cells.delta;
    case "gpu":
      return cells.gpu;
    case "started":
      return cells.started;
    case "launcher":
      return joined(cells.launcher);
    case "host":
      return joined(cells.host);
    case "commit":
      return joined(cells.commit);
    case "tags":
      return joined(cells.tags);
    default:
      return null;
  }
}

/** Sort by one column; missing values last in either direction; ties keep the list order. */
export function sortItems(items: readonly Identity[], data: TaskRuns, col: string | null, dir: TableSortDir): Identity[] {
  if (col === null) return [...items];
  return items
    .map((item, i) => ({ item, i, v: sortValue(item, identityCells(item, data), col) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === b.v ? a.i - b.i : a.v === null ? 1 : -1;
      const d = typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : String(a.v).localeCompare(String(b.v));
      return d !== 0 ? (dir === "asc" ? d : -d) : a.i - b.i;
    })
    .map((x) => x.item);
}

export function columnsKey(project: string, task: string): string {
  return `hx.runs.columns.${project}/${task}`;
}

export function loadHiddenColumns(project: string, task: string): string[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(columnsKey(project, task)) ?? "[]");
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function saveHiddenColumns(project: string, task: string, hidden: readonly string[]): void {
  localStorage.setItem(columnsKey(project, task), JSON.stringify(hidden));
}
