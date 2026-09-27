/**
 * Sticky top bar from the ui-v4 mockup: brand, screen tabs, find button, theme toggle.
 *
 * Tabs: Overview always; Task, Run and Examples point at the last task, run and example
 * pair the user opened (kept in localStorage) and are hidden until there is one.
 */
import { Link, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";

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

function loadRecent(): RecentTargets {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as RecentTargets) : {};
  } catch {
    return {};
  }
}

function useRecentTargets(pathname: string, search: Record<string, unknown>): RecentTargets {
  const [recent, setRecent] = useState<RecentTargets>(() => updateRecent(loadRecent(), pathname, search));
  useEffect(() => {
    setRecent((prev) => {
      const next = updateRecent(prev, pathname, search);
      try {
        localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
        // storage disabled: tabs still work for this page
      }
      return next;
    });
  }, [pathname, search]);
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
