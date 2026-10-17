/**
 * Run actions (spec 4.3, 8A.8): Compare and Rerun in the run header; Re-infer,
 * Re-evaluate, Stop (two clicks within 3 s) and Archive in a ⋯ menu. Each sends a
 * command_id. A run waiting in a queue can only be cancelled; a run on an unreachable
 * host offers Reconnect; a lost run makes Rerun the main action.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { CleanedArtifact, EvalReport } from "../../api/models";
import { hasScope, mayAct } from "../../api/scopes";
import { useMe, HOST_EVENT_INVALIDATES, REMOTE_RUN_INVALIDATES, RUN_EVENT_INVALIDATES } from "../../api/queries";
import { Icon } from "../../chrome/Icon";
import { menuArrowKeys, useMenuFocus } from "../../chrome/menuFocus";
import { useArmed } from "../../run/useArmed";
import { AppLink, hrefs, useNavigateHref } from "./links";
import { ErrorBox } from "./QueryState";
import { ReevalSummary } from "./ReevalSummary";
import type { RunPhase } from "./remote";
import { ACTIVE_STATUSES, type HostState, type RunRecord, type RunRef } from "./types";
import { useAction } from "./useAction";
import { cleanedArtifact } from "./cleaned";

export interface RunActionsProps {
  record: RunRecord;
  phase?: RunPhase;
  /** Authoritative routing availability from RunDetail, independent of connection state. */
  served: boolean;
  hostsLoaded?: boolean;
  /**
   * The hub's name for the run's host (`runHostRow(...)?.name`); null for a hub run or while
   * the hosts list is not loaded. Never `executor.host` (the machine's hostname).
   */
  hostName?: string | null;
  hostRepair?: string | null;
  /** Only a successfully loaded task with an infer stage enables Re-infer. */
  inferStage?: boolean;
  cleaned?: readonly CleanedArtifact[];
  /** Examples page link; null: no other config (disabled); undefined: no Compare button. */
  compareHref?: string | null;
}

/** Close a popover on Escape or a press outside `ref`. */
function useDismiss(open: boolean, close: () => void, ref: { current: HTMLElement | null }): void {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close, ref]);
}

export function RunActions({
  record,
  phase = "local",
  hostName = null,
  hostRepair = null,
  served,
  hostsLoaded = false,
  inferStage,
  cleaned = [],
  compareHref,
}: RunActionsProps) {
  const checkpoint = record.artifacts.filter(artifact=>artifact.kind==="checkpoint").at(-1);
  const checkpointCleaned = checkpoint && cleanedArtifact(checkpoint.path,record.environment_id,cleaned);
  const me=useMe();
  const writable=hasScope(me.data,"launch");
  const ownerAction=mayAct(me.data,record.owner);
  const executable=writable && (phase !== "local" || hasScope(me.data,"admin"));
  const navigate = useNavigateHref();
  const id = record.run_id;
  const label = hostName ?? record.host;
  const refresh = phase === "local" ? RUN_EVENT_INVALIDATES : REMOTE_RUN_INVALIDATES;
  const openNew = (made: RunRef) => navigate(hrefs.run(made.run_id));
  const rerun = useAction<RunRef>({ send: (_: void, opts) => api.rerun(id, opts), invalidate: refresh, onSuccess: openNew });
  const reinfer = useAction<RunRef>({
    send: (_: void, opts) => api.reinfer(id, undefined, opts),
    invalidate: refresh,
    onSuccess: openNew,
  });
  const [report, setReport] = useState<{ runId: string; value: EvalReport } | null>(null);
  const reeval = useAction({
    send: async (_: void, opts) => {
      const runId = id;
      return { runId, value: await api.reevalRun(runId, {}, opts) };
    },
    invalidate: refresh,
    onSuccess: setReport,
  });
  const stop = useAction({
    send: (onlyQueued: boolean, opts) => (onlyQueued ? api.cancelQueuedRun(id, opts) : api.stop(id, opts)),
    invalidate: refresh,
  });
  const reconnect = useAction<HostState>({
    send: (_: void, opts) => api.connectHost(hostName ?? "", opts),
    invalidate: HOST_EVENT_INVALIDATES,
  });
  const archive = useAction({
    send: (on: boolean, opts) => api.archiveRun(id, on, opts),
    invalidate: [...refresh, ["taskRuns"]],
  });
  const active = ACTIVE_STATUSES.has(record.status);
  const { armed, arm, disarm } = useArmed([id, record.status, served, phase]);
  const [menu, setMenu] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const moreButton = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setMenu(false), []);
  useDismiss(menu, close, wrap);
  useMenuFocus(menu, menuRef, moreButton);
  const unavailable = hostsLoaded
    ? "No configured host serves this run's environment"
    : "The hosts list is not loaded; this run's serving host is unknown";
  const error = rerun.error ?? reinfer.error ?? reeval.error ?? stop.error ?? reconnect.error ?? archive.error;
  const waiting = phase === "queued" || phase === "pending";
  const lost = phase === "lost";
  return (
    <div className="run-actions">
      <div className="actions" title={!writable ? "Launch scope required" : !ownerAction ? "Stop and archive need the run owner or admin" : undefined}>
        {waiting ? (
          <button
            type="button"
            className="btn primary"
            disabled={!ownerAction || !served || stop.pending}
            onClick={() => stop.run(true)}
            title={
              !served ? unavailable : phase === "pending" && record.executor.slurm_job_id
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
              disabled={!hasScope(me.data,"admin") || !served || !!hostRepair || reconnect.pending || hostName === null}
              onClick={() => {
                if (hostName !== null && !hostRepair) reconnect.run();
              }}
              title={
                !served ? unavailable : hostRepair ? hostRepair : hostName === null
                  ? hostsLoaded ? unavailable : `The hosts list is not loaded, so the hub's name for ${record.host} is unknown`
                  : `Try ${hostName} again now`
              }
            >
              Reconnect
            </button>
            <button type="button" className="btn" disabled title={!served ? unavailable : `${label} is unreachable`}>
              Stop
            </button>
          </>
        ) : (
          <>
            {compareHref === undefined ? null : compareHref ? (
              <AppLink className="btn" href={compareHref} title="Compare examples with the best other config">
                Compare
              </AppLink>
            ) : (
              <button type="button" className="btn" disabled title="No other scored config in this task">
                Compare
              </button>
            )}
            <button
              type="button"
              className={lost ? "btn primary" : "btn"}
              disabled={!executable || !served || rerun.pending}
              onClick={() => rerun.run()}
              title={!served ? unavailable : "Run again with the same command, code, and seed"}
            >
              Rerun
            </button>
            <div className="menu-wrap" ref={wrap}>
              <button
                ref={moreButton}
                type="button"
                className="btn icon"
                aria-label="More actions"
                aria-haspopup="menu"
                aria-expanded={menu}
                title="Re-infer, re-evaluate, stop, archive"
                onClick={() => setMenu((open) => !open)}
              >
                <Icon name="more" />
              </button>
              {menu ? (
                <div ref={menuRef} className="menu" role="menu" aria-label="Run actions" onKeyDown={menuArrowKeys}>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!executable || !served || reinfer.pending || !!checkpointCleaned || inferStage !== true}
                    onClick={() => {
                      close();
                      reinfer.run();
                    }}
                    title={
                      !served ? unavailable : checkpointCleaned ? "Checkpoint was deleted by cleanup" : inferStage === true
                        ? "Run the infer stage again on this run's checkpoint"
                        : inferStage === false ? "Task has no infer stage" : "Infer stage not loaded"
                    }
                  >
                    Re-infer
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!writable || !served || reeval.pending}
                    onClick={() => {
                      close();
                      setReport(null);
                      reeval.run();
                    }}
                    title={!served ? unavailable : "Re-score saved predictions with the current metric versions"}
                  >
                    Re-evaluate
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!ownerAction || !served || !active || stop.pending}
                    onClick={() => {
                      if (!ownerAction || !served || !active || stop.pending) return;
                      if (armed) {
                        disarm();
                        close();
                        stop.run(false);
                      } else {
                        arm();
                      }
                    }}
                    onBlur={disarm}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") disarm();
                    }}
                    title={!served ? unavailable : active ? (armed ? "Click again to stop this run" : "Stop this run") : "The run is not active"}
                  >
                    {armed ? "Stop ✓?" : "Stop"}
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!ownerAction || !served || archive.pending}
                    onClick={() => {
                      close();
                      archive.run(!record.archived);
                    }}
                    title={!served ? unavailable : record.archived ? "Show this run in lists again" : "Hide this run from lists; nothing is deleted"}
                  >
                    {record.archived ? "Unarchive" : "Archive"}
                  </button>
                </div>
              ) : null}
            </div>
          </>
        )}
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {report?.runId === id ? <ReevalSummary report={report.value} /> : null}
    </div>
  );
}
