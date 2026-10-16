/**
 * The hovered x shared by every LineChart of one section (spec 4.2: synced crosshair).
 * A tiny external store keyed by group id; a group's value is dropped with its last reader.
 */
import { useCallback, useSyncExternalStore } from "react";

type Listener = () => void;
const values = new Map<string, number | null>();
const listeners = new Map<string, Set<Listener>>();

/** Set the hovered x of `groupId` (null hides the crosshair) and notify its charts. */
export function setCrosshair(groupId: string, x: number | null): void {
  if ((values.get(groupId) ?? null) === x) return;
  values.set(groupId, x);
  for (const listener of listeners.get(groupId) ?? []) listener();
}

/** The hovered x of `groupId`, or null. */
export function getCrosshair(groupId: string): number | null {
  return values.get(groupId) ?? null;
}

/** `[x, setX]` for one crosshair group. */
export function useCrosshair(groupId: string): [number | null, (x: number | null) => void] {
  const subscribe = useCallback(
    (listener: Listener) => {
      const set = listeners.get(groupId) ?? new Set<Listener>();
      listeners.set(groupId, set);
      set.add(listener);
      return () => {
        set.delete(listener);
        if (set.size === 0) {
          listeners.delete(groupId);
          values.delete(groupId);
        }
      };
    },
    [groupId],
  );
  const x = useSyncExternalStore(subscribe, () => getCrosshair(groupId), () => null);
  const setX = useCallback((v: number | null) => setCrosshair(groupId, v), [groupId]);
  return [x, setX];
}
