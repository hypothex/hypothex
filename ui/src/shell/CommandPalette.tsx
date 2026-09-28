/**
 * ⌘K / Ctrl+K palette (ui-v4 mockup): go to a task or run, copy a repo or dataset path,
 * switch colour mode. Items are filtered by every typed word (case-insensitive) over the
 * group, title, subtitle and hidden keywords (hypothesis, tags, paths).
 */
import { useNavigate } from "@tanstack/react-router";
import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import type { ProjectInfo, RunRecord, TaskSummary } from "../api/models";
import { useProjects, useRuns, useTasks } from "../api/queries";
import { toggleTheme } from "./ThemeToggle";

export type NavTarget =
  | { to: "/" }
  | { to: "/t/$project/$task"; params: { project: string; task: string } }
  | { to: "/r/$runId"; params: { runId: string } };

export interface CommandItem {
  group: "Go to" | "Tasks" | "Runs" | "Paths" | "Commands";
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
  projects: ProjectInfo[];
  tasks: TaskSummary[];
  runs: RunRecord[];
}

/** Most runs listed in the palette (newest first, archived runs left out). */
export const MAX_RUNS = 50;

const clip = (s: string, n = 60): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Build the palette items, grouped in display order. */
export function buildCommands(data: CommandData, h: CommandHandlers): CommandItem[] {
  const items: CommandItem[] = [
    { group: "Go to", title: "Overview", subtitle: "all projects", run: () => h.go({ to: "/" }) },
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
    const who = r.seed === null ? r.status : `seed ${r.seed}, ${r.status}`;
    items.push({
      group: "Runs",
      title: r.run_id,
      subtitle: `${clip(r.hypothesis || r.task || r.project)}, ${who}`,
      keywords: [r.hypothesis, r.project, r.task ?? "", r.created_by, ...r.tags, r.cwd].join(" "),
      run: () => h.go({ to: "/r/$runId", params: { runId: r.run_id } }),
    });
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

function PaletteDialog({ onClose, onToast }: { onClose: () => void; onToast: (msg: string) => void }) {
  const navigate = useNavigate();
  const projects = useProjects();
  const tasks = useTasks();
  const runs = useRuns({ limit: 200 });
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => input.current?.focus(), []);

  const all = useMemo(
    () =>
      buildCommands(
        { projects: projects.data ?? [], tasks: tasks.data ?? [], runs: runs.data ?? [] },
        {
          go: (target) => void navigate(target),
          copy: (text) => {
            void navigator.clipboard?.writeText(text).catch(() => undefined);
            onToast(`Copied ${text}`);
          },
          toggleTheme: () => void toggleTheme(),
        },
      ),
    [projects.data, tasks.data, runs.data, navigate, onToast],
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
