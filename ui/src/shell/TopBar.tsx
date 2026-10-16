/**
 * Top bar (spec section 3): breadcrumb from the route, the command palette button (⌘K),
 * the live-updates indicator and `New run` (the existing Launch dialog).
 */
import { useQuery } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { type ReactElement, useState } from "react";

import { api } from "../api/client";
import { useStreamStatus } from "../api/events";
import type { RunDetail } from "../api/models";
import { queryKeys, useProjects } from "../api/queries";
import { shortId } from "../charts/valueFormat";
import { Button } from "../chrome/Button";
import { Icon } from "../chrome/Icon";
import { LaunchDialog } from "../launch/LaunchDialog";
import { AppLink, hrefs, useNavigateHref } from "../pages/components/links";
import "./shell.css";

export interface Crumb {
  label: string;
  href?: string;
}

export interface RunCrumb {
  project: string;
  task: string | null;
  name: string;
}

const decode = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};
const segments = (pathname: string): string[] => pathname.split("/").filter(Boolean).map(decode);

/** The breadcrumb of a pathname; `run` is the open run's project, task and name once loaded. */
export function crumbsFor(pathname: string, run?: RunCrumb | null): Crumb[] {
  const p = segments(pathname);
  if (p.length === 0) return [{ label: "Home" }];
  switch (p[0]) {
    case "t": {
      const project = p[1] ?? "";
      const task = p[2] ?? "";
      const out: Crumb[] = [{ label: project }, { label: task, href: hrefs.task(project, task) }];
      if (p[3] === "edit" && p[4]) out.push({ label: p[4] === "new" ? "new view" : `edit ${p[4]}` });
      return out;
    }
    case "r":
      if (!run) return [{ label: shortId(p[1] ?? "") }];
      return [
        { label: run.project },
        ...(run.task ? [{ label: run.task, href: hrefs.task(run.project, run.task) }] : []),
        { label: run.name },
      ];
    case "x":
      return [{ label: "Examples" }, { label: `${shortId(p[1] ?? "")} vs ${shortId(p[2] ?? "")}` }];
    case "s":
      return [{ label: p[1] ?? "" }, { label: `sweep ${p[2] ?? ""}` }];
    case "hosts":
      return [{ label: "Hosts" }];
    case "queue":
      return [{ label: "Queue" }];
    default:
      return [{ label: "Not found" }];
  }
}

/** "⌘K" on Apple platforms, "Ctrl K" elsewhere. */
export function paletteShortcut(platform: string = navigator.platform): string {
  return /Mac|iPhone|iPad/.test(platform) ? "⌘K" : "Ctrl K";
}

function LiveDot(): ReactElement {
  const status = useStreamStatus();
  const word = status === "ready" ? "live" : status === "offline" ? "offline" : "connecting";
  const name = status === "ready" ? "on" : status === "offline" ? "off" : "reconnecting";
  const title =
    status === "ready"
      ? "Live updates on"
      : status === "offline"
        ? "Live updates are off: data is not live, reload to reconnect"
        : "Reconnecting live updates: data is not live yet";
  return (
    <span className={`live ${word}`} role="status" aria-label={`Live updates ${name}`} title={title}>
      <i aria-hidden="true" />
      {word}
    </span>
  );
}

interface LaunchTarget {
  project: string;
  task: string | null;
  repo: string;
}

export interface TopBarProps {
  onSearch: () => void;
  navOpen: boolean;
  onToggleNav: () => void;
}

export function TopBar({ onSearch, navOpen, onToggleNav }: TopBarProps): ReactElement {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const parts = segments(pathname);
  const runId = parts[0] === "r" ? (parts[1] ?? null) : null;
  // the run page reads the same key, so this adds no request
  const run = useQuery<RunDetail>({
    queryKey: queryKeys.run(runId ?? ""),
    queryFn: ({ signal }) => api.run(runId ?? "", signal),
    enabled: runId !== null,
  });
  const record = runId !== null ? run.data?.record : undefined;
  const crumbs = crumbsFor(
    pathname,
    record ? { project: record.project, task: record.task, name: record.name ?? shortId(record.run_id) } : null,
  );

  const projects = useProjects();
  const navigate = useNavigateHref();
  const [launching, setLaunching] = useState(false);
  const routeProject = parts[0] === "t" || parts[0] === "s" ? parts[1] : record?.project;
  const routeTask = parts[0] === "t" ? (parts[2] ?? null) : (record?.task ?? null);
  const info = routeProject ? projects.data?.find((p) => p.project === routeProject) : projects.data?.[0];
  const target: LaunchTarget | null = info ? { project: info.project, task: routeProject ? routeTask : null, repo: info.repo } : null;

  return (
    <header className="top">
      {navOpen ? null : (
        <Button variant="ghost" size="sm" iconOnly icon="queue" aria-label="Show navigation" title="Show navigation (⌘.)" onClick={onToggleNav} />
      )}
      <nav className="crumb" aria-label="Breadcrumb">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <span key={`${i}-${c.label}`} style={{ display: "contents" }}>
              {i > 0 ? (
                <span className="sep" aria-hidden="true">
                  /
                </span>
              ) : null}
              {last ? <b aria-current="page">{c.label}</b> : c.href ? <AppLink href={c.href}>{c.label}</AppLink> : <span>{c.label}</span>}
            </span>
          );
        })}
      </nav>
      <span className="sp" />
      <button className="search" id="findBtn" type="button" aria-haspopup="dialog" onClick={onSearch}>
        <Icon name="search" size={13} />
        <span>Search runs, tasks, paths</span>
        <kbd>{paletteShortcut()}</kbd>
      </button>
      <LiveDot />
      <Button
        variant="primary"
        icon="plus"
        disabled={target === null}
        title={target ? `New run in ${target.project}${target.task ? ` / ${target.task}` : ""}` : "No project yet: run hx init"}
        onClick={() => setLaunching(true)}
      >
        New run
      </Button>
      {launching && target ? (
        <LaunchDialog
          project={target.project}
          task={target.task}
          repo={target.repo}
          onClose={() => setLaunching(false)}
          onLaunched={(records) => {
            setLaunching(false);
            const first = records[0];
            if (first) navigate(hrefs.run(first.run_id));
          }}
        />
      ) : null}
    </header>
  );
}
