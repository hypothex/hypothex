/** Route hrefs (contract section 4) and an in-app link that works with or without a router. */
import { useRouter } from "@tanstack/react-router";
import {
  type AnchorHTMLAttributes,
  type MouseEvent,
  createContext,
  useCallback,
  useContext,
} from "react";

export type Navigate = (href: string) => void;

/** Overrides navigation (tests, embedding). `null` means "use the router". */
export const NavigateContext = createContext<Navigate | null>(null);

const enc = encodeURIComponent;

function withSearch(path: string, search: Record<string, string | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== "") qs.set(key, value);
  }
  const query = qs.toString();
  return query ? `${path}?${query}` : path;
}

export const hrefs = {
  overview: (): string => "/",
  /** `/t/<project>/<task>`, with `?tab=` unless `tab` is Charts (the default). */
  task: (project: string, task: string, tab?: string): string =>
    withSearch(`/t/${enc(project)}/${enc(task)}`, { tab: tab === "charts" ? undefined : tab }),
  /** A saved view's tab: `?tab=view:<view>`. */
  taskView: (project: string, task: string, view: string): string =>
    withSearch(`/t/${enc(project)}/${enc(task)}`, { tab: `view:${view}` }),
  /** A sweep in its task's Sweeps tab. */
  taskSweep: (project: string, task: string, sweepId: string): string =>
    withSearch(`/t/${enc(project)}/${enc(task)}`, { tab: "sweeps", sweep: sweepId }),
  edit: (project: string, task: string, view: string): string =>
    `/t/${enc(project)}/${enc(task)}/edit/${enc(view)}`,
  run: (runId: string, search: { tab?: string; log?: string; example?: string } = {}): string =>
    withSearch(`/r/${enc(runId)}`, { ...search, tab: search.tab === "overview" ? undefined : search.tab }),
  examples: (a: string, b: string, metric?: string): string =>
    withSearch(`/x/${enc(a)}/${enc(b)}`, { metric }),
  hosts: (): string => "/hosts",
  queue: (): string => "/queue",
};

interface HistoryLike {
  history: { push: (href: string) => void };
}

/** Navigate to an href: context override, else the router, else a full page load. */
export function useNavigateHref(): Navigate {
  const override = useContext(NavigateContext);
  const router = useRouter({ warn: false }) as unknown as HistoryLike | null | undefined;
  return useCallback(
    (href: string) => {
      if (override) override(href);
      else if (router) router.history.push(href);
      else window.location.assign(href);
    },
    [override, router],
  );
}

/** A left click with no modifier keys (a modified click opens a new tab instead). */
export function isPlainClick(e: {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): boolean {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

export type AppLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
};

/** True for a path the SPA routes (Home, Task, Run, Examples, Sweep, Hosts, Queue); `/api/…` is left to the browser. */
export function isAppPath(pathname: string): boolean {
  return /^\/($|[trsx]\/|hosts$|queue$)/.test(pathname);
}

/**
 * Click handler for a container of plain `<a href>` links (panel bodies).
 *
 * Panels (Parts 2–3) render plain links so they work without a router; this turns a
 * plain left click on a same-origin app link into in-app navigation. Modified clicks,
 * `target`/`download` links, other origins, `/api/…` paths and clicks a link already
 * handled (for example an `AppLink`) keep the browser's behaviour.
 */
export function useInAppLinks(): (e: MouseEvent<HTMLElement>) => void {
  const navigate = useNavigateHref();
  return useCallback(
    (e: MouseEvent<HTMLElement>) => {
      if (e.defaultPrevented || !isPlainClick(e)) return;
      const link = (e.target as Element | null)?.closest?.("a[href]");
      if (!(link instanceof HTMLAnchorElement) || !e.currentTarget.contains(link)) return;
      if (link.target || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin || !isAppPath(url.pathname)) return;
      e.preventDefault();
      navigate(`${url.pathname}${url.search}${url.hash}`);
    },
    [navigate],
  );
}

/** An `<a href>` that navigates in-app on a plain click and keeps browser behaviour otherwise. */
export function AppLink({ href, onClick, target, children, ...rest }: AppLinkProps) {
  const navigate = useNavigateHref();
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || target || !isPlainClick(e)) return;
    e.preventDefault();
    navigate(href);
  };
  return (
    <a {...rest} href={href} target={target} onClick={handle}>
      {children}
    </a>
  );
}
