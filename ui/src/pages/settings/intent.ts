import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { auth } from "../../api/auth";
import { newCommandId } from "../../api/client";
import type { ActionOptions } from "../../api/models";
import { shouldRetry } from "../components/useAction";

/** A component-local immutable intent; retries retain both arguments and identity. */
export function useIntent<A, T>(send: (arg: A, options: ActionOptions) => Promise<T>, success?: (result: T, arg: A) => void, options: { retry?: boolean } = {}) {
  const generation = useSyncExternalStore(auth.subscribe, auth.snapshot).generation;
  const sequence = useRef(0);
  const active = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => () => { sequence.current++; controller.current?.abort(); active.current = false; }, []);
  useEffect(() => { sequence.current++; controller.current?.abort(); active.current = false; setPending(false); setError(null); }, [generation]);
  const run = async (input: A): Promise<void> => {
    if (active.current) return;
    const arg = structuredClone(input);
    controller.current?.abort(); controller.current = new AbortController();
    const original = auth.capture();
    const credential = { ...original, signal: AbortSignal.any([original.signal, controller.current.signal]) };
    const serial = ++sequence.current;
    const current = (): boolean => auth.current(credential.generation) && sequence.current === serial;
    const opts = { command_id: newCommandId(), created_by: "human", credential, signal: credential.signal };
    active.current = true; setPending(true); setError(null);
    for (let attempt = 0; ; attempt++) {
      if (!current()) return;
      try {
        const result = await send(arg, opts);
        if (current()) { active.current = false; setPending(false); success?.(result, arg); }
        return;
      } catch (caught) {
        const err = caught instanceof Error ? caught : new Error("Request failed");
        if (!current()) return;
        if (options.retry !== false && shouldRetry(attempt, err)) continue;
        active.current = false; setPending(false); setError(err); return;
      }
    }
  };
  return { run, pending, error, generation, reset: (): void => { sequence.current++; controller.current?.abort(); active.current = false; setPending(false); setError(null); } };
}
