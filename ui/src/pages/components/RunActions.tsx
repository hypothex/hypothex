/**
 * Run actions (spec 8.3.3, 8A.8): rerun, re-infer, re-evaluate, stop; each with a
 * command_id. A run waiting in a queue can only be cancelled; a run on an unreachable host
 * offers Reconnect; a lost run makes Rerun the main action.
 */
import { api } from "../../api/client";
import { HOST_EVENT_INVALIDATES, REMOTE_RUN_INVALIDATES, RUN_EVENT_INVALIDATES } from "../../api/queries";
import { hrefs, useNavigateHref } from "./links";
import { ErrorBox } from "./QueryState";
import type { RunPhase } from "./remote";
import { ACTIVE_STATUSES, type HostState, type RunRecord, type RunRef } from "./types";
import { useAction } from "./useAction";

export interface RunActionsProps {
  record: RunRecord;
  phase?: RunPhase;
  /**
   * The hub's name for the run's host (`runHostRow(...)?.name`); null for a hub run or while
   * the hosts list is not loaded. Never `executor.host`: that is the machine's hostname, and
   * `POST /api/v1/hosts/<hostname>/connect` names no configured host.
   */
  hostName?: string | null;
}

export function RunActions({ record, phase = "local", hostName = null }: RunActionsProps) {
  const navigate = useNavigateHref();
  const id = record.run_id;
  const label = hostName ?? record.host;
  const refresh = phase === "local" ? RUN_EVENT_INVALIDATES : REMOTE_RUN_INVALIDATES;
  const openNew = (made: RunRef) => navigate(hrefs.run(made.run_id));
  const rerun = useAction<RunRef>({
    send: (_: void, opts) => api.rerun(id, opts),
    invalidate: refresh,
    onSuccess: openNew,
  });
  const reinfer = useAction<RunRef>({
    send: (_: void, opts) => api.reinfer(id, undefined, opts),
    invalidate: refresh,
    onSuccess: openNew,
  });
  const reeval = useAction({ send: (_: void, opts) => api.reevalRun(id, {}, opts), invalidate: refresh });
  const stop = useAction({ send: (_: void, opts) => api.stop(id, opts), invalidate: refresh });
  const reconnect = useAction<HostState>({
    send: (_: void, opts) => api.connectHost(hostName ?? "", opts),
    invalidate: HOST_EVENT_INVALIDATES,
  });
  const active = ACTIVE_STATUSES.has(record.status);
  const error = rerun.error ?? reinfer.error ?? reeval.error ?? stop.error ?? reconnect.error;
  const waiting = phase === "queued" || phase === "pending";
  const lost = phase === "lost";
  return (
    <div>
      <div className="actions">
        {waiting ? (
          <button
            type="button"
            className="btn primary"
            disabled={stop.pending}
            onClick={() => stop.run()}
            title={
              phase === "pending" && record.executor.slurm_job_id
                ? `Cancel SLURM job ${record.executor.slurm_job_id}`
                : `Remove from the ${label} queue`
            }
          >
            Cancel
          </button>
        ) : phase === "stale" ? (
          <>
            <button
              type="button"
              className="btn primary"
              disabled={reconnect.pending || hostName === null}
              onClick={() => {
                if (hostName !== null) reconnect.run();
              }}
              title={
                hostName === null
                  ? `The hosts list is not loaded, so the hub's name for ${record.host} is unknown`
                  : `Try ${hostName} again now`
              }
            >
              Reconnect
            </button>
            <button type="button" className="btn" disabled title={`${label} is unreachable`}>
              Stop
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className={lost ? "btn primary" : "btn"}
              disabled={rerun.pending}
              onClick={() => rerun.run()}
              title="Run again with the same command, code, and seed"
            >
              Rerun
            </button>
            <button
              type="button"
              className="btn"
              disabled={reinfer.pending}
              onClick={() => reinfer.run()}
              title="Run the infer stage again on this run's checkpoint"
            >
              Re-infer
            </button>
            <button
              type="button"
              className={lost ? "btn" : "btn primary"}
              disabled={reeval.pending}
              onClick={() => reeval.run()}
              title="Re-score saved predictions with the current metric versions"
            >
              Re-evaluate
            </button>
            <button
              type="button"
              className="btn"
              disabled={!active || stop.pending}
              onClick={() => stop.run()}
              title={active ? "Stop this run" : "The run is not active"}
            >
              Stop
            </button>
          </>
        )}
      </div>
      {error ? <ErrorBox error={error} /> : null}
    </div>
  );
}
