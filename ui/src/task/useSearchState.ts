/**
 * The page URL's search string as React state, with or without a router.
 *
 * Under the app's TanStack router it reads and writes the router's history, so links,
 * the back button and the router see every change; in tests and embeds without a router it
 * uses `window.history`. Writes replace the history entry unless `push` is set (tab
 * switches push, filter typing replaces).
 */
import { useRouter } from "@tanstack/react-router";
import { useCallback, useMemo, useSyncExternalStore } from "react";

export type SearchPatch = Record<string, string | null | undefined>;
export type SetSearch = (patch: SearchPatch, opts?: { push?: boolean }) => void;

interface HistoryLike {
  location: { pathname: string; search: string; hash: string };
  push: (href: string) => void;
  replace: (href: string) => void;
  subscribe: (listener: () => void) => () => void;
}

const windowListeners = new Set<() => void>();
const notifyWindow = (): void => {
  for (const listener of windowListeners) listener();
};

const windowHistory: HistoryLike = {
  get location() {
    return window.location;
  },
  push: (href) => {
    window.history.pushState(null, "", href);
    notifyWindow();
  },
  replace: (href) => {
    window.history.replaceState(window.history.state, "", href);
    notifyWindow();
  },
  subscribe: (listener) => {
    windowListeners.add(listener);
    window.addEventListener("popstate", listener);
    return () => {
      windowListeners.delete(listener);
      window.removeEventListener("popstate", listener);
    };
  },
};

/** `search` with `patch` applied: `null`, `undefined` or `""` removes a key; other keys keep their order. */
export function applySearch(search: string, patch: SearchPatch): string {
  const params = new URLSearchParams(search);
  for (const [key, value] of Object.entries(patch)) {
    if (value === null || value === undefined || value === "") params.delete(key);
    else params.set(key, value);
  }
  const out = params.toString();
  return out ? `?${out}` : "";
}

/** The current search params and a setter that patches them in place. */
export function useSearchState(): [URLSearchParams, SetSearch] {
  const router = useRouter({ warn: false }) as unknown as { history: HistoryLike } | null | undefined;
  const history = router?.history ?? windowHistory;
  const search = useSyncExternalStore(history.subscribe, () => history.location.search, () => "");
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const set = useCallback<SetSearch>(
    (patch, opts = {}) => {
      const { pathname, search: current, hash } = history.location;
      const next = `${pathname}${applySearch(current, patch)}${hash}`;
      if (opts.push) history.push(next);
      else history.replace(next);
    },
    [history],
  );
  return [params, set];
}
