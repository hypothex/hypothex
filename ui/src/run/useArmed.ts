/** A two-click confirm: the first click arms, a second within `ms` acts (spec 4.3 Stop). */
import { useEffect, useState } from "react";

export const ARM_MS = 3000;

/** `armed` resets when any of `resetKeys` changes, and `ms` after it was armed. */
export function useArmed(resetKeys: readonly unknown[], ms: number = ARM_MS): { armed: boolean; arm: () => void; disarm: () => void } {
  const [armed, setArmed] = useState(false);
  const key = JSON.stringify(resetKeys);
  useEffect(() => {
    setArmed(false);
  }, [key]);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), ms);
    return () => clearTimeout(timer);
  }, [armed, ms]);
  return { armed, arm: () => setArmed(true), disarm: () => setArmed(false) };
}
