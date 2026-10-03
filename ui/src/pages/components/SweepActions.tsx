/**
 * Sweep actions (contract section 4): Copy as CLI (the same `hx sweep` command), Cancel
 * queued (`POST .../cancel_queued`), Add seeds (`POST .../extend`: every cell × the next
 * seeds). Each POST carries one `command_id` per click, so a retry is not a second action.
 */
import { type ReactElement, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { RunRecord, SweepSpec } from "../../api/models";
import { REMOTE_RUN_INVALIDATES } from "../../api/queries";
import { ErrorBox } from "./QueryState";
import { MAX_NEW_SEEDS, nextSeeds, parseSeedCount, sweepCli } from "./SweepModel";
import { useAction } from "./useAction";

export interface SweepActionsProps {
  project: string;
  sweepId: string;
  spec: SweepSpec;
  /** Queued runs of the sweep now (summary counts). */
  queued: number;
  /** Param combinations; Add seeds adds this many runs per new seed. */
  cellCount: number;
  /** The sweep's runs, for `--gpus`, `--queue` and `-H` in Copy as CLI. */
  runs: readonly RunRecord[];
}

type CopyState = "idle" | "copied" | "failed";

const COPY_TEXT: Record<CopyState, string> = { idle: "Copy as CLI", copied: "Copied", failed: "Clipboard blocked" };

export function SweepActions({ project, sweepId, spec, queued, cellCount, runs }: SweepActionsProps): ReactElement {
  const [copy, setCopy] = useState<CopyState>("idle");
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(String(Math.max(1, spec.seeds.length)));
  useEffect(() => {
    if (copy === "idle") return;
    const timer = setTimeout(() => setCopy("idle"), 1500);
    return () => clearTimeout(timer);
  }, [copy]);
  const cancel = useAction({
    send: (_: void, opts) => api.cancelQueued(project, sweepId, opts),
    invalidate: REMOTE_RUN_INVALIDATES,
  });
  const extend = useAction({
    send: (seeds: number[], opts) => api.extendSweep(project, sweepId, seeds, opts),
    invalidate: REMOTE_RUN_INVALIDATES,
    onSuccess: () => setOpen(false),
  });
  const cli = sweepCli(spec, runs);
  const n = parseSeedCount(count);
  const seeds = n === null ? [] : nextSeeds(spec.seeds, n);
  const doCopy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(cli);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };
  return (
    <div className="sw-actions">
      <div className="actions">
        <button type="button" className="btn" title={cli} onClick={() => void doCopy()}>
          {COPY_TEXT[copy]}
        </button>
        <button
          type="button"
          className="btn"
          disabled={queued === 0 || cancel.pending}
          title={queued === 0 ? "No queued runs" : `Cancel the ${queued} queued run${queued === 1 ? "" : "s"}`}
          onClick={() => cancel.run()}
        >
          Cancel queued
        </button>
        <button
          type="button"
          className="btn primary"
          aria-expanded={open}
          title="Add seeds to every cell"
          onClick={() => setOpen((v) => !v)}
        >
          Add seeds
        </button>
      </div>
      {open ? (
        <form
          className="add-seeds"
          aria-label="Add seeds"
          onSubmit={(e) => {
            e.preventDefault();
            if (seeds.length > 0) extend.run(seeds);
          }}
        >
          <label>
            new seeds
            <input
              type="number"
              min={1}
              max={MAX_NEW_SEEDS}
              value={count}
              aria-label="New seeds per cell"
              onChange={(e) => setCount(e.target.value)}
            />
          </label>
          <span className="small">
            {seeds.length > 0
              ? `${seeds.join(", ")} × ${cellCount} cells = ${seeds.length * cellCount} runs`
              : `1–${MAX_NEW_SEEDS}`}
          </span>
          <button type="submit" className="btn primary" disabled={seeds.length === 0 || extend.pending}>
            {`Add ${seeds.length * cellCount} runs`}
          </button>
        </form>
      ) : null}
      {cancel.error ? <ErrorBox error={cancel.error} /> : null}
      {extend.error ? <ErrorBox error={extend.error} /> : null}
    </div>
  );
}
