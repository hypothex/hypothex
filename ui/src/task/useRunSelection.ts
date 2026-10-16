/**
 * Run-list state for one task, in the URL so a view is shareable (spec 4.2, §6):
 * `?filter=` filter text, `?group=run` (each run instead of by config), `?sort=<key>:<dir>`,
 * `?hide=<id>,<id>` hidden identities, `?sup=1` (show runs tagged `superseded`). Defaults
 * stay out of the URL.
 *
 * An identity is a config group (By config) or a run (Each run). It gets one colour in
 * every panel: `colorFor(id, visibleIdentities(selection, data))`.
 */
import { useCallback, useMemo } from "react";
import type { TaskGroup, TaskRun, TaskRuns } from "../api/models";
import { parseFilter } from "../lib/runFilter";
import { type SearchPatch, useSearchState } from "./useSearchState";

export type SortDir = "asc" | "desc";
export type GroupMode = "config" | "run";

export interface Selection {
  filter: string;
  group: GroupMode;
  sort: { key: string; dir: SortDir };
  hidden: string[];
  showSuperseded: boolean;
}

export interface SelectionDefaults {
  /** Direction of the default primary sort: best first (`desc` when higher is better). */
  sortDir: SortDir;
}

export const SORT_PRIMARY = "primary";
export const SORT_CREATED = "created";
export const SUPERSEDED_TAG = "superseded";

/** One row of the run list: a config group or a single run. */
export interface Identity {
  id: string;
  kind: "group" | "run";
  /** Display name (a run: base name and ` · seed N` unless renamed). */
  name: string;
  /** Name without the seed: what a rename edits. */
  baseName: string;
  runs: TaskRun[];
  /** The config group (for a run: the group it belongs to). */
  group: TaskGroup | null;
  /** Primary value: group mean over seeds, or the run's own value. */
  value: number | null;
  /** Seed standard deviation of a group with more than one scored seed. */
  sd: number | null;
  hidden: boolean;
}

/** Short label of a score key: `top1/value` → `top1`, `reported/test-a.model-x.top10` → `test-a.model-x.top10`. */
export function keyLabel(key: string): string {
  const cut = key.indexOf("/");
  if (cut < 0) return key;
  const rest = key.slice(cut + 1);
  return rest === "value" || rest === "" ? key.slice(0, cut) : rest;
}

/** The run's explicit name when renamed, else its derived name. */
export function runBaseName(run: TaskRun): string {
  return run.renamed ? run.name : run.derived_name;
}

/** What a run row shows: a renamed run's name, else the derived name with ` · seed N`. */
export function runLabel(run: TaskRun): string {
  const base = runBaseName(run);
  return run.renamed || run.seed === null ? base : `${base} · seed ${run.seed}`;
}

/** The most recently created run. */
export function latestRun(runs: readonly TaskRun[]): TaskRun | undefined {
  return runs.reduce<TaskRun | undefined>((a, r) => (a === undefined || r.created_at > a.created_at ? r : a), undefined);
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A score of an identity: the group's mean for a group, the run's value for a run. */
export function scoreOf(item: Identity, key: string): number | null {
  if (item.kind === "group" && item.group) return item.group.scores[key] ?? null;
  const values = item.runs.map((r) => r.scores[key]).filter(finite);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

/** Every run of the identity is tagged `superseded`. */
export function isSuperseded(item: Identity): boolean {
  return item.runs.every((r) => r.tags.includes(SUPERSEDED_TAG));
}

/** All identities of a task, unsorted, unfiltered, none hidden. */
export function identities(data: TaskRuns, group: GroupMode): Identity[] {
  const groupOf = new Map(data.groups.map((g) => [g.group_id, g]));
  if (group === "run") {
    return data.runs.map(
      (run): Identity => ({
        id: run.run_id,
        kind: "run",
        name: runLabel(run),
        baseName: runBaseName(run),
        runs: [run],
        group: groupOf.get(run.group_id) ?? null,
        value: run.primary,
        sd: null,
        hidden: false,
      }),
    );
  }
  const byId = new Map(data.runs.map((r) => [r.run_id, r]));
  const covered = new Set<string>();
  const out: Identity[] = [];
  for (const g of data.groups) {
    const runs = g.run_ids.map((id) => byId.get(id)).filter((r): r is TaskRun => r !== undefined);
    if (runs.length === 0) continue;
    for (const r of runs) covered.add(r.run_id);
    out.push({
      id: g.group_id,
      kind: "group",
      name: g.name,
      baseName: g.name,
      runs,
      group: g,
      value: g.primary?.mean ?? null,
      sd: g.primary && g.primary.n > 1 ? g.primary.std : null,
      hidden: false,
    });
  }
  // runs the server listed in no group: one identity per group id, never dropped
  const orphans = new Map<string, TaskRun[]>();
  for (const r of data.runs) if (!covered.has(r.run_id)) orphans.set(r.group_id, [...(orphans.get(r.group_id) ?? []), r]);
  for (const [id, runs] of orphans) {
    const name = runBaseName(runs[0] as TaskRun);
    out.push({ id, kind: "group", name, baseName: name, runs, group: null, value: null, sd: null, hidden: false });
  }
  return out;
}

function sortValue(item: Identity, key: string): number | string | null {
  if (key === SORT_PRIMARY) return item.value;
  if (key === SORT_CREATED) return latestRun(item.runs)?.created_at ?? null;
  return scoreOf(item, key);
}

/** Missing values last in either direction; ties: newest first, then id. */
export function compareIdentities(a: Identity, b: Identity, sort: Selection["sort"]): number {
  const va = sortValue(a, sort.key);
  const vb = sortValue(b, sort.key);
  if (va === null || vb === null) {
    if (va !== vb) return va === null ? 1 : -1;
  } else {
    const d = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
    if (d !== 0) return sort.dir === "asc" ? d : -d;
  }
  const ca = latestRun(a.runs)?.created_at ?? "";
  const cb = latestRun(b.runs)?.created_at ?? "";
  return cb.localeCompare(ca) || a.id.localeCompare(b.id);
}

/** The run list in display order: filtered, superseded removed unless shown, sorted, `hidden` set. */
export function listIdentities(sel: Selection, data: TaskRuns): Identity[] {
  const matches = sel.filter.trim() === "" ? () => true : parseFilter(sel.filter);
  const hidden = new Set(sel.hidden);
  return identities(data, sel.group)
    .filter((i) => sel.showSuperseded || !isSuperseded(i))
    .filter((i) => i.runs.some((r) => matches(r)))
    .sort((a, b) => compareIdentities(a, b, sel.sort))
    .map((i) => ({ ...i, hidden: hidden.has(i.id) }));
}

/** Ids drawn in the panels, in list order: the colour order of `colorFor`. */
export function visibleIdentities(sel: Selection, data: TaskRuns): string[] {
  return listIdentities(sel, data)
    .filter((i) => !i.hidden)
    .map((i) => i.id);
}

/** The selection a URL holds; unknown or malformed values fall back to the defaults. */
export function parseSelection(params: URLSearchParams, defaults: SelectionDefaults): Selection {
  const sort = params.get("sort") ?? "";
  const cut = sort.lastIndexOf(":");
  const key = cut > 0 ? sort.slice(0, cut) : "";
  const dir = sort.slice(cut + 1);
  return {
    filter: params.get("filter") ?? "",
    group: params.get("group") === "run" ? "run" : "config",
    sort: key !== "" && (dir === "asc" || dir === "desc") ? { key, dir } : { key: SORT_PRIMARY, dir: defaults.sortDir },
    hidden: (params.get("hide") ?? "").split(",").filter(Boolean),
    showSuperseded: params.get("sup") === "1",
  };
}

/**
 * The selection of a URL with no selection keys, best first: what every page shows by default
 * (the run page uses it to give a run the same colour as the task page).
 */
export function defaultSelection(higherIsBetter: boolean): Selection {
  return parseSelection(new URLSearchParams(), { sortDir: higherIsBetter ? "desc" : "asc" });
}

/** URL keys for a patch; values equal to the defaults are removals. */
export function selectionSearch(patch: Partial<Selection>, defaults: SelectionDefaults): SearchPatch {
  const out: SearchPatch = {};
  if (patch.filter !== undefined) out.filter = patch.filter.trim() === "" ? null : patch.filter;
  if (patch.group !== undefined) out.group = patch.group === "run" ? "run" : null;
  if (patch.sort !== undefined) {
    const isDefault = patch.sort.key === SORT_PRIMARY && patch.sort.dir === defaults.sortDir;
    out.sort = isDefault ? null : `${patch.sort.key}:${patch.sort.dir}`;
  }
  if (patch.hidden !== undefined) out.hide = patch.hidden.length ? [...new Set(patch.hidden)].join(",") : null;
  if (patch.showSuperseded !== undefined) out.sup = patch.showSuperseded ? "1" : null;
  return out;
}

/** The selection of the page URL and a patcher (replaces the history entry). */
export function useRunSelection(
  defaults: Partial<SelectionDefaults> = {},
): [Selection, (patch: Partial<Selection>) => void] {
  const [params, setSearch] = useSearchState();
  const sortDir = defaults.sortDir ?? "desc";
  const selection = useMemo(() => parseSelection(params, { sortDir }), [params, sortDir]);
  const update = useCallback(
    (patch: Partial<Selection>) => setSearch(selectionSearch(patch, { sortDir })),
    [setSearch, sortDir],
  );
  return [selection, update];
}
