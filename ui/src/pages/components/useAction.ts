/** A POST action with a per-click `command_id`, safe to retry after a dropped connection. */
import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, newCommandId } from "../../api/client";
import { auth } from "../../api/auth";
import type { ActionOptions } from "../../api/models";

export const ACTION_RETRY_DELAY_MS = 250;

/** Retry only requests with no HTTP answer (the server may not have seen them), twice. */
export function shouldRetry(failureCount: number, error: Error): boolean {
  if (error.name === "AbortError") return false;
  const unanswered = !(error instanceof ApiError) || error.status === 0;
  return failureCount < 2 && unanswered;
}

export interface UseActionOptions<T, A> {
  /** Call one `api.*` action; pass `opts` through so every attempt has the same `command_id`. */
  send: (arg: A, opts: ActionOptions) => Promise<T>;
  invalidate?: readonly QueryKey[];
  onSuccess?: (data: T) => void;
}

export interface Action<A> {
  run: (arg: A) => void;
  pending: boolean;
  error: Error | null;
}

interface Vars<A> {
  commandId: string;
  arg: A;
  generation: number;
}

export function useAction<T = unknown, A = void>({
  send,
  invalidate = [],
  onSuccess,
}: UseActionOptions<T, A>): Action<A> {
  const client = useQueryClient();
  const mutation = useMutation<T, Error, Vars<A>>({
    mutationFn: async ({ commandId, arg, generation }) => {
      if (!auth.current(generation)) throw new DOMException("Action superseded", "AbortError");
      const result = await send(arg, { command_id: commandId, created_by: "human" });
      if (!auth.current(generation)) throw new DOMException("Action superseded", "AbortError");
      return result;
    },
    retry: shouldRetry,
    retryDelay: ACTION_RETRY_DELAY_MS,
    // Mark the keys stale and refetch in the background: the button and the caller's
    // `onSuccess` (often a navigation) must not wait for every refetch to land.
    onSuccess: (data, { generation }) => {
      if (!auth.current(generation)) return;
      for (const queryKey of invalidate) void client.invalidateQueries({ queryKey });
      onSuccess?.(data);
    },
  });
  return {
    run: (arg: A) => mutation.mutate({ commandId: newCommandId(), arg, generation: auth.snapshot().generation }),
    pending: mutation.isPending,
    error: mutation.error,
  };
}
