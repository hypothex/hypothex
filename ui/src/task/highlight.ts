/**
 * The identity hovered or focused in the runs sidebar. Every chart of the page reads it
 * (`useHighlight()`) and passes it as `highlight`, so that identity's marks stand out.
 */
import { useSyncExternalStore } from "react";

let current: string | null = null;
const listeners = new Set<() => void>();

/** Highlight an identity (`null`: none). */
export function setHighlight(id: string | null): void {
  if (id === current) return;
  current = id;
  for (const listener of listeners) listener();
}

/** The highlighted identity, or null. */
export function getHighlight(): string | null {
  return current;
}

const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** The highlighted identity as React state. */
export function useHighlight(): string | null {
  return useSyncExternalStore(subscribe, getHighlight, () => null);
}
