/**
 * The v5 frame (spec section 3): 216 px nav (brand, NavTree, hub version, theme), the top
 * bar, the routed page; the command palette and the one chart tooltip are mounted here.
 * ⌘. / Ctrl+. hides or shows the nav (kept in localStorage).
 */
import { Link, Outlet } from "@tanstack/react-router";
import { type ReactElement, useCallback, useEffect, useState } from "react";

import { useStreamStatus } from "../api/events";
import { useHubEnvironment } from "../api/queries";
import { TooltipHost } from "../charts/Tooltip";
import { cx } from "../lib/cx";
import { CommandPalette } from "./CommandPalette";
import { NavTree } from "./NavTree";
import { ThemeToggle } from "./ThemeToggle";
import { TopBar } from "./TopBar";
import "./shell.css";

export const NAV_KEY = "hx-nav";

function readNavOpen(): boolean {
  try {
    return localStorage.getItem(NAV_KEY) !== "0";
  } catch {
    return true;
  }
}

function Brand(): ReactElement {
  return (
    <Link className="brand" to="/" aria-label="Hypothex, home">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <rect x="1" y="9" width="3" height="8" rx="1" fill="currentColor" opacity=".35" />
        <rect x="5.5" y="5" width="3" height="12" rx="1" fill="currentColor" opacity=".6" />
        <rect x="10" y="1" width="3" height="16" rx="1" fill="currentColor" />
        <circle cx="15.5" cy="3" r="1.8" fill="var(--c3)" />
      </svg>
      Hypothex
    </Link>
  );
}

function HubVersion(): ReactElement {
  const env = useHubEnvironment();
  const status = useStreamStatus();
  const version = env.data?.hx_version;
  return (
    <span className={cx("hub", status === "ready" && "live")} title="Hub version">
      <i aria-hidden="true" />
      {typeof version === "string" ? `hub · v${version}` : "hub"}
    </span>
  );
}

export function AppShell(): ReactElement {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(readNavOpen);
  const toggleNav = useCallback(() => setNavOpen((open) => !open), []);

  useEffect(() => {
    try {
      localStorage.setItem(NAV_KEY, navOpen ? "1" : "0");
    } catch {
      // storage disabled: the nav still toggles for this page
    }
  }, [navOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.metaKey || e.ctrlKey) && e.key === ".") {
        e.preventDefault();
        toggleNav();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [toggleNav]);

  return (
    <div className={cx("app", !navOpen && "nav-off")}>
      {navOpen ? (
        <aside className="nav">
          <Brand />
          <NavTree />
          <div className="nav-foot">
            <HubVersion />
            <ThemeToggle />
          </div>
        </aside>
      ) : null}
      <div className="main">
        <TopBar onSearch={() => setPaletteOpen(true)} navOpen={navOpen} onToggleNav={toggleNav} />
        <main className="app-page">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <TooltipHost />
    </div>
  );
}
