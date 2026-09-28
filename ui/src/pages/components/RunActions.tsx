/** Run actions (spec 8.3.3): rerun, re-infer, re-evaluate, stop; each with a command_id. */
import { api } from "../../api/client";
import { RUN_EVENT_INVALIDATES } from "../../api/queries";
import { hrefs, useNavigateHref } from "./links";
import { ErrorBox } from "./QueryState";
import { ACTIVE_STATUSES, type RunRecord, type RunRef } from "./types";
import { useAction } from "./useAction";

export function RunActions({ record }: { record: RunRecord }) {
  const navigate = useNavigateHref();
  const id = record.run_id;
  const refresh = RUN_EVENT_INVALIDATES;
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
  const active = ACTIVE_STATUSES.has(record.status);
  const error = rerun.error ?? reinfer.error ?? reeval.error ?? stop.error;
  return (
    <div>
      <div className="actions">
        <button
          type="button"
          className="btn"
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
          className="btn primary"
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
      </div>
      {error ? <ErrorBox error={error} /> : null}
    </div>
  );
}
