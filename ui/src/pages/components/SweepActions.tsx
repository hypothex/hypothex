/**
 * Sweep actions (contract section 4): Copy as CLI (the same `hx sweep` command), Cancel
 * queued (`POST .../cancel_queued`), Add seeds (`POST .../extend`: every cell × the next
 * seeds). Each POST carries one `command_id` per click, so a retry is not a second action.
 *
 * The hub saves an extend's seeds in the sweep before it issues their runs, so after a
 * failed extend the refreshed summary may list them already. Until an extend goes through,
 * the seeds sent in failed tries are not counted as taken: the retry proposes (and sends)
 * them again, and the hub issues only their missing runs, instead of growing the sweep by
 * the seeds after them.
 */
import { type ReactElement, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { RunRecord, SweepSpec, SweepIssuance } from "../../api/models";
import { REMOTE_RUN_INVALIDATES } from "../../api/queries";
import { issuanceActive, issuanceCancellable } from "../../api/sweepIssuance";
import { ErrorBox } from "./QueryState";
import { MAX_NEW_SEEDS, nextSeeds, parseSeedCount, sweepCli } from "./SweepModel";
import { useAction } from "./useAction";

export interface SweepActionsProps {
  project: string;
  sweepId: string;
  spec: SweepSpec;
  /** Queued runs of the sweep now (summary counts). */
  queued: number;
  issuance?: SweepIssuance | null;
  /** Param combinations; Add seeds adds this many runs per new seed. */
  cellCount: number;
  /** The sweep's runs, for `--gpus`, `--queue` and `-H` in Copy as CLI. */
  runs: readonly RunRecord[];
  /** Opens the Launch dialog for "Rerun sweep"; no button without it. */
  onRerun?: () => void;
}

type CopyState = "idle" | "copied" | "failed";

const COPY_TEXT: Record<CopyState, string> = { idle: "Copy as CLI", copied: "Copied", failed: "Clipboard blocked" };

export function SweepActions({
  project,
  sweepId,
  spec,
  queued,
  issuance,
  cellCount,
  runs,
  onRerun,
}: SweepActionsProps): ReactElement {
  const [copy, setCopy] = useState<CopyState>("idle");
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(String(Math.min(MAX_NEW_SEEDS, Math.max(1, spec.seeds.length))));
  // seeds sent by an extend that has not gone through yet (see above)
  const [tried, setTried] = useState<readonly number[]>([]);
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
    onSuccess: () => {
      setTried([]);
      setOpen(false);
    },
  });
  const active = issuanceActive(issuance);
  const cancellable = issuanceCancellable(issuance);
  const cancelDisabled = (queued === 0 && !cancellable) || cancel.pending ||
    (active && issuance?.cancel_requested === true) || issuance?.state === "preparing";
  const cancelTitle = cancellable
    ? "Cancel remaining issuance and queued runs; running members continue"
    : queued === 0 ? "No queued runs" : `Cancel the ${queued} queued run${queued === 1 ? "" : "s"}`;
  const cli = sweepCli(spec, runs);
  const n = parseSeedCount(count);
  const seeds = n === null ? [] : nextSeeds(spec.seeds.filter((s) => !tried.includes(s)), n);
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
        {onRerun ? (
          <button
            type="button"
            className="btn"
            title="Launch the best cell again on new seeds, on any host"
            onClick={onRerun}
          >
            Rerun sweep
          </button>
        ) : null}
        <button type="button" className="btn" title={cli} onClick={() => void doCopy()}>
          {COPY_TEXT[copy]}
        </button>
        <button
          type="button"
          className="btn"
          disabled={cancelDisabled}
          title={cancelTitle}
          onClick={() => cancel.run()}
        >
          Cancel queued
        </button>
        <button
          type="button"
          className="btn primary"
          disabled={active || cancel.pending || extend.pending}
          aria-expanded={open}
          title="Add seeds to every cell"
          onClick={() => {
            extend.reset();
            setOpen((v) => !v);
          }}
        >
          Add seeds
        </button>
      </div>
      {issuance?.resume ? (
        <button
          type="button"
          className="btn"
          title={issuance.resume.message}
          disabled={active || cancel.pending || extend.pending}
          onClick={() => {
            if (issuance.resume && !active && !cancel.pending) extend.run([...issuance.resume.seeds]);
          }}
        >
          Resume
        </button>
      ) : null}
      {open ? (
        <form
          className="add-seeds"
          aria-label="Add seeds"
          onSubmit={(e) => {
            e.preventDefault();
            if (seeds.length === 0 || active || cancel.pending || extend.pending) return;
            setTried((t) => [...t, ...seeds.filter((s) => !t.includes(s))]);
            extend.run(seeds);
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
          <button type="submit" className="btn primary" disabled={active || cancel.pending || seeds.length === 0 || extend.pending}>
            {`Add ${seeds.length * cellCount} runs`}
          </button>
        </form>
      ) : null}
      {cancel.error ? <div><ErrorBox error={cancel.error} /><button type="button" className="btn link" onClick={cancel.reset}>Dismiss cancel error</button></div> : null}
      {extend.error ? <div><ErrorBox error={extend.error} /><button type="button" className="btn link" onClick={extend.reset}>Dismiss extend error</button></div> : null}
    </div>
  );
}
