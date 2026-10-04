/**
 * Sticky top bar from the ui-v4 mockup: brand, screen tabs, find button, theme toggle.
 *
 * Tabs: Overview always; Task, Run and Examples point at the last task, run and example
 * pair the user opened (kept in localStorage) and are hidden until there is one. A target
 * is saved only once the page's own read of it succeeds, so a 404 never becomes a tab.
 */
import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { useStreamStatus } from "../api/events";
import { queryKeys } from "../api/queries";
import { ThemeToggle } from "./ThemeToggle";

export type Screen = "overview" | "task" | "run" | "examples";

export interface RecentTargets {
  task?: { project: string; task: string };
  run?: { runId: string };
  examples?: { a: string; b: string; metric?: string };
}

export const RECENT_KEY = "hx-recent";

const seg = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

/** Which screen a pathname belongs to (the view editor counts as the task screen). */
export function screenOf(pathname: string): Screen | null {
  if (pathname === "/" || pathname === "") return "overview";
  if (/^\/t\/[^/]+\/[^/]+(\/edit\/[^/]+)?\/?$/.test(pathname)) return "task";
  if (/^\/r\/[^/]+\/?$/.test(pathname)) return "run";
  if (/^\/x\/[^/]+\/[^/]+\/?$/.test(pathname)) return "examples";
  return null;
}

/** Remember the task, run or example pair in `pathname` (other screens leave `prev` as is). */
export function updateRecent(prev: RecentTargets, pathname: string, search: Record<string, unknown>): RecentTargets {
  const parts = pathname.split("/").filter(Boolean).map(seg);
  switch (screenOf(pathname)) {
    case "task":
      return { ...prev, task: { project: parts[1] ?? "", task: parts[2] ?? "" } };
    case "run":
      return { ...prev, run: { runId: parts[1] ?? "" } };
    case "examples": {
      const metric = typeof search.metric === "string" ? search.metric : undefined;
      return { ...prev, examples: { a: parts[1] ?? "", b: parts[2] ?? "", metric } };
    }
    default:
      return prev;
  }
}

type Json = Record<string, unknown>;

const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const isName = (v: unknown): v is string => typeof v === "string" && v !== "";

/** The well-formed entries of a stored value; anything else (old or corrupt) is dropped. */
export function parseRecent(value: unknown): RecentTargets {
  if (!isObject(value)) return {};
  const out: RecentTargets = {};
  const { task, run, examples } = value;
  if (isObject(task) && isName(task.project) && isName(task.task)) {
    out.task = { project: task.project, task: task.task };
  }
  if (isObject(run) && isName(run.runId)) out.run = { runId: run.runId };
  if (isObject(examples) && isName(examples.a) && isName(examples.b)) {
    out.examples = { a: examples.a, b: examples.b };
    if (isName(examples.metric)) out.examples.metric = examples.metric;
  }
  return out;
}

function loadRecent(): RecentTargets {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? parseRecent(JSON.parse(raw)) : {};
  } catch {
    return {};
  }
}

/**
 * The reads whose success shows the target in `pathname` exists: the ones its page makes
 * (Task and the view editor read the leaderboard; Run and Examples read their runs).
 */
export function confirmKeys(pathname: string): QueryKey[] {
  const { task, run, examples } = updateRecent({}, pathname, {});
  if (task) return [queryKeys.leaderboard(task.project, task.task)];
  if (run) return [queryKeys.run(run.runId)];
  if (examples) return [queryKeys.run(examples.a), queryKeys.run(examples.b)];
  return [];
}

/**
 * True once every read in `keys` has succeeded. It only watches the cache (an observer
 * here would fetch, or pass its options on to the page's query).
 */
function useReadsOk(keys: QueryKey[]): boolean {
  const client = useQueryClient();
  const cache = client.getQueryCache();
  const subscribe = useCallback((onChange: () => void) => cache.subscribe(onChange), [cache]);
  const ok = () => keys.every((key) => client.getQueryState(key)?.status === "success");
  return useSyncExternalStore(subscribe, ok, ok);
}

function useRecentTargets(pathname: string, search: Record<string, unknown>): RecentTargets {
  const [recent, setRecent] = useState<RecentTargets>(loadRecent);
  const confirmed = useReadsOk(confirmKeys(pathname));
  useEffect(() => {
    if (!confirmed) return;
    setRecent((prev) => {
      const next = updateRecent(prev, pathname, search);
      try {
        localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
        // storage disabled: tabs still work for this page
      }
      return next;
    });
  }, [confirmed, pathname, search]);
  return recent;
}

/** The brand mark: the best idea's band, a diamond on it, a dot for the baseline. */
function BrandMark() {
  return (
    <svg width="22" height="18" viewBox="0 0 22 18" aria-hidden="true">
      <rect x="9" y="1" width="8" height="16" style={{ fill: "var(--best-wash)" }} />
      <line x1="9" y1="1" x2="9" y2="17" style={{ stroke: "var(--best-edge)" }} />
      <line x1="17" y1="1" x2="17" y2="17" style={{ stroke: "var(--best-edge)" }} />
      <line x1="1" y1="9" x2="21" y2="9" style={{ stroke: "var(--ink)", strokeWidth: 1.4 }} />
      <rect x="10" y="5" width="5.6" height="5.6" transform="rotate(45 12.8 7.8)" style={{ fill: "var(--best)" }} />
      <circle cx="4" cy="9" r="2.6" style={{ fill: "var(--ink)" }} />
    </svg>
  );
}

/** "⌘K" on Apple platforms, "Ctrl K" elsewhere. */
export function paletteShortcut(platform: string = navigator.platform): string {
  return /Mac|iPhone|iPad/.test(platform) ? "⌘K" : "Ctrl K";
}

/** A dot and word while live updates are down; nothing while they are live. */
function LiveStatus() {
  const status = useStreamStatus();
  if (status === "ready") return null;
  const offline = status === "offline";
  return (
    <span
      className={offline ? "live off" : "live"}
      role="status"
      aria-label={`Live updates ${offline ? "off" : "reconnecting"}`}
      title={
        offline
          ? "Live updates are off: data is not live, reload to reconnect"
          : "Reconnecting live updates: data is not live yet"
      }
    >
      {offline ? "● offline" : "● connecting"}
    </span>
  );
}

export interface HeaderProps {
  /** Opens the command palette. */
  onFind?: () => void;
}

export function Header({ onFind }: HeaderProps) {
  const location = useRouterState({ select: (s) => s.location });
  const search = location.search as Record<string, unknown>;
  const recent = useRecentTargets(location.pathname, search);
  const here = screenOf(location.pathname);
  const current = (s: Screen) => (here === s ? ("page" as const) : undefined);

  return (
    <header className="bar">
      <div className="bar-in">
        <Link className="brand" to="/" aria-label="Hypothex, overview">
          <BrandMark />
          <span>Hypothex</span>
        </Link>
        <nav className="tabs" aria-label="Screens">
          <Link to="/" aria-current={current("overview")}>
            Overview
          </Link>
          {recent.task && (
            <Link
              to="/t/$project/$task"
              params={recent.task}
              aria-current={current("task")}
              title={`${recent.task.project} / ${recent.task.task}`}
            >
              Task
            </Link>
          )}
          {recent.run && (
            <Link to="/r/$runId" params={recent.run} aria-current={current("run")} title={recent.run.runId}>
              Run
            </Link>
          )}
          {recent.examples && (
            <Link
              to="/x/$a/$b"
              params={{ a: recent.examples.a, b: recent.examples.b }}
              search={{ metric: recent.examples.metric }}
              aria-current={current("examples")}
              title={`${recent.examples.a} vs ${recent.examples.b}`}
            >
              Examples
            </Link>
          )}
        </nav>
        <div className="bar-r">
          <LiveStatus />
          <button className="find" id="findBtn" type="button" aria-haspopup="dialog" onClick={onFind}>
            <span>Find a run, task or path</span>
            <kbd>{paletteShortcut()}</kbd>
          </button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
