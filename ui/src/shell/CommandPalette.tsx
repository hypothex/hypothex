/**
 * ⌘K / Ctrl+K palette: go to Home, Hosts, Queue, a task or a run (titled by its display
 * name), copy a repo or dataset path, switch colour mode. Items are filtered by every typed
 * word (case-insensitive) over the group, title, subtitle and hidden keywords (run id, name,
 * hypothesis, tags, params, paths). Typed text of two or more characters also asks the hub
 * for runs whose stored name or id contains it (spec 5.2), so renamed runs outside the
 * newest list are found too.
 */
import { sweepCrumb } from "../pages/components/remote";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { ProjectInfo, RunRecord, RunsQuery, TaskRuns, TaskSummary } from "../api/models";
import { queryKeys, useHubEnvironment, useProjects, useRuns, useTasks } from "../api/queries";
import { firstClause, shortId } from "../pages/components/format";
import { withSeed } from "../run/RunName";
import { toggleTheme } from "./ThemeToggle";
import "./kept.css";

export type NavTarget =
  | { to: "/" }
  | { to: "/hosts" }
  | { to: "/queue" }
  | { to: "/t/$project/$task"; params: { project: string; task: string } }
  | { to: "/r/$runId"; params: { runId: string } }
  | { to: "/s/$project/$id"; params: { project: string; id: string } };

export interface CommandItem {
  group: "Go to" | "Tasks" | "Runs" | "Sweeps" | "Paths" | "Commands";
  title: string;
  subtitle: string;
  keywords?: string;
  run: () => void;
}

export interface CommandHandlers {
  go: (target: NavTarget) => void;
  copy: (text: string) => void;
  toggleTheme: () => void;
}

export interface CommandData {
  hubEnvironmentId?: string | null;
  projects: ProjectInfo[];
  tasks: TaskSummary[];
  runs: RunRecord[];
  /** Run id → display name (derived or renamed), from task-runs lists already cached. */
  names?: ReadonlyMap<string, string>;
}

/** Most runs listed in the palette (newest first, archived runs left out). */
export const MAX_RUNS = 50;

/** Most runs the hub returns for a typed name search. */
const SEARCH_LIMIT = 20;
/** Typed text shorter than this does not search the hub. */
const SEARCH_MIN = 2;
/** The hub's `q` length limit. */
const SEARCH_MAX = 200;
/** Wait after the last keystroke before searching the hub. */
const SEARCH_DELAY_MS = 150;

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

/**
 * Run display names from every task-runs list already in the query cache (no extra request),
 * as the run page shows them: a rename as typed, else the derived name with its seed.
 */
export function cachedRunNames(entries: readonly (readonly [unknown, TaskRuns | undefined])[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const [, data] of entries) {
    for (const run of data?.runs ?? []) out.set(run.run_id, run.renamed ? run.name : withSeed(run.derived_name, run.seed));
  }
  return out;
}

/** A run's palette title: its display name, else its own name, else its hypothesis clause, with the seed. */
export function runCommandTitle(r: RunRecord, names?: ReadonlyMap<string, string>): string {
  const known = names?.get(r.run_id) ?? r.name?.trim();
  if (known) return known;
  return withSeed(r.hypothesis ? firstClause(r.hypothesis, r.run_id, 60) : `run ${shortId(r.run_id)}`, r.seed);
}

/** Build the palette items, grouped in display order. */
export function buildCommands(data: CommandData, h: CommandHandlers): CommandItem[] {
  const items: CommandItem[] = [
    { group: "Go to", title: "Home", subtitle: "all projects", run: () => h.go({ to: "/" }) },
    { group: "Go to", title: "Hosts", subtitle: "GPUs and connections", run: () => h.go({ to: "/hosts" }) },
    { group: "Go to", title: "Queue", subtitle: "queued runs", run: () => h.go({ to: "/queue" }) },
  ];
  for (const t of data.tasks) {
    items.push({
      group: "Tasks",
      title: `${t.project} / ${t.name}`,
      subtitle: plural(t.n_runs, "run"),
      keywords: t.description,
      run: () => h.go({ to: "/t/$project/$task", params: { project: t.project, task: t.name } }),
    });
  }
  const runs = data.runs.filter((r) => !r.archived).slice(0, MAX_RUNS);
  for (const r of runs) {
    items.push({
      group: "Runs",
      title: runCommandTitle(r, data.names),
      subtitle: `${r.project} / ${r.task ?? "—"} · ${shortId(r.run_id)} · ${r.status}`,
      keywords: [r.run_id, r.name ?? "", r.hypothesis, r.project, r.task ?? "", r.created_by, ...r.tags,
        ...Object.entries(r.params).map(([key, value]) => `${key}=${value}`), r.cwd].join(" "),
      run: () => h.go({ to: "/r/$runId", params: { runId: r.run_id } }),
    });
  }
  const sweeps = new Set<string>();
  for (const record of runs) {
    const sweep = sweepCrumb(record, data.hubEnvironmentId ?? null);
    const key = JSON.stringify([record.project, sweep?.id]);
    if (!sweep?.href || sweeps.has(key)) continue;
    sweeps.add(key);
    items.push({ group: "Sweeps", title: `${record.project} / ${sweep.id}`, subtitle: record.task ?? "",
      run: () => h.go({ to: "/s/$project/$id", params: { project: record.project, id: sweep.id } }) });
  }
  for (const p of data.projects) {
    items.push({ group: "Paths", title: `Copy ${p.project} repo`, subtitle: p.repo, run: () => h.copy(p.repo) });
  }
  const seen = new Set<string>();
  for (const r of runs) {
    for (const d of r.datasets) {
      const where = d.host === "local" ? d.path : `${d.host}:${d.path}`;
      if (seen.has(where)) continue;
      seen.add(where);
      items.push({ group: "Paths", title: `Copy ${d.name} data`, subtitle: where, run: () => h.copy(where) });
    }
  }
  items.push({ group: "Commands", title: "Switch colour mode", subtitle: "light or dark", run: h.toggleTheme });
  return items;
}

/** Keep items whose text contains every whitespace-separated word of `query`. */
export function filterCommands(items: CommandItem[], query: string): CommandItem[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return items;
  return items.filter((c) => {
    const hay = `${c.group} ${c.title} ${c.subtitle} ${c.keywords ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** Hub search hits first (they matched the typed text), then the newest runs not among them. */
function mergeRuns(hits: readonly RunRecord[], recent: readonly RunRecord[]): RunRecord[] {
  const seen = new Set(hits.map((r) => r.run_id));
  return [...hits, ...recent.filter((r) => !seen.has(r.run_id))];
}

/** The typed text, trimmed and held until typing pauses; null when too short to search. */
function useSearchText(query: string): string | null {
  const text = query.trim().slice(0, SEARCH_MAX);
  const [settled, setSettled] = useState(text);
  useEffect(() => {
    const t = setTimeout(() => setSettled(text), SEARCH_DELAY_MS);
    return () => clearTimeout(t);
  }, [text]);
  return settled.length >= SEARCH_MIN ? settled : null;
}

function PaletteDialog({ onClose, onToast }: { onClose: () => void; onToast: (msg: string) => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const projects = useProjects();
  const environment = useHubEnvironment();
  const tasks = useTasks();
  const runs = useRuns({ limit: 200 });
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const searchText = useSearchText(query);
  const searchQuery: RunsQuery = { q: searchText ?? "", limit: SEARCH_LIMIT };
  const found = useQuery({
    queryKey: queryKeys.runs(searchQuery),
    queryFn: ({ signal }) => api.runs(searchQuery, signal),
    enabled: searchText !== null,
  });
  const names = useMemo(() => cachedRunNames(qc.getQueriesData<TaskRuns>({ queryKey: ["taskRuns"] })), [qc, runs.data]);
  const hits = searchText !== null ? found.data : undefined;

  useEffect(() => input.current?.focus(), []);

  const all = useMemo(
    () =>
      buildCommands(
        { projects: projects.data ?? [], tasks: tasks.data ?? [], runs: mergeRuns(hits ?? [], runs.data ?? []), names, hubEnvironmentId: typeof environment.data?.environment_id === "string" ? environment.data.environment_id : null },
        {
          go: (target) => void navigate(target),
          copy: (text) => {
            void navigator.clipboard?.writeText(text).catch(() => undefined);
            onToast(`Copied ${text}`);
          },
          toggleTheme: () => void toggleTheme(),
        },
      ),
    [projects.data, tasks.data, runs.data, hits, names, environment.data, navigate, onToast],
  );
  const items = useMemo(() => filterCommands(all, query), [all, query]);
  const loading = projects.isPending || tasks.isPending || runs.isPending;

  useEffect(() => {
    document.getElementById(`po${sel}`)?.scrollIntoView?.({ block: "nearest" });
  }, [sel]);

  const runItem = (i: number) => {
    const item = items[i];
    if (!item) return;
    onClose();
    item.run();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(items.length - 1, s + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(0, s - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runItem(sel);
    } else if (e.key === "Tab") {
      // Modal: the input is the dialog's only tab stop, so Tab must not leave it.
      e.preventDefault();
      input.current?.focus();
    }
  };

  const rows: ReactNode[] = [];
  let lastGroup = "";
  items.forEach((c, i) => {
    if (c.group !== lastGroup) {
      rows.push(
        <li className="grp" role="presentation" key={`g-${c.group}`}>
          {c.group}
        </li>,
      );
      lastGroup = c.group;
    }
    rows.push(
      <li
        className="it"
        role="option"
        id={`po${i}`}
        key={`${c.group}-${c.title}-${c.subtitle}`}
        aria-selected={i === sel}
        onMouseMove={() => setSel(i)}
        onClick={() => runItem(i)}
      >
        <span>{c.title}</span>
        <small>{c.subtitle}</small>
      </li>,
    );
  });

  return (
    <div
      className="pal on"
      role="dialog"
      aria-modal="true"
      aria-label="Find and run commands"
      onKeyDown={onKeyDown}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="pal-box">
        <input
          ref={input}
          className="pal-in"
          placeholder="Find a run, task, path or command"
          autoComplete="off"
          role="combobox"
          aria-label="Find a run, task, path or command"
          aria-expanded="true"
          aria-autocomplete="list"
          aria-controls="palList"
          aria-activedescendant={items.length ? `po${sel}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSel(0);
          }}
        />
        <ul className="pal-list" id="palList" role="listbox">
          {rows.length ? rows : <li className="grp">{loading ? "Loading…" : "Nothing matches"}</li>}
          {rows.length > 0 && loading && <li className="grp">Loading…</li>}
        </ul>
        <div className="pal-foot">
          <span>
            <kbd>↑</kbd> <kbd>↓</kbd> move
          </span>
          <span>
            <kbd>Enter</kbd> open
          </span>
          <span>
            <kbd>Esc</kbd> close
          </span>
        </div>
      </div>
    </div>
  );
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Palette plus its ⌘K / Ctrl+K shortcut and the "Copied …" toast. Mounted once, in the shell. */
export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (toast === null) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  const close = () => {
    onOpenChange(false);
    document.getElementById("findBtn")?.focus();
  };

  return (
    <>
      {open && <PaletteDialog onClose={close} onToast={setToast} />}
      <div className={toast ? "toast on" : "toast"} role="status" aria-live="polite">
        {toast}
      </div>
    </>
  );
}
