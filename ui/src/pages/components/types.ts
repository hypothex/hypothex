/**
 * API shapes the pages read, and the run-status sets they share.
 *
 * Every shape comes from `ui/src/api/models.ts`, the single hand-written copy of the
 * phase 1b contract; this module only adds page names for three of them and the sets.
 */
import type { RunStatus, TaskKindInfo, ViewDocument, ViewQueryResult } from "../../api/models";

export type * from "../../api/models";

/** `GET .../views/{name}`: the stored YAML and the resolved view. */
export type ViewDetail = ViewDocument;
/** `POST .../views/query`. */
export type QueryResponse = ViewQueryResult;
/** `GET .../kind`: the task kind and its run-detail panels. */
export type KindInfo = TaskKindInfo;

/** The part of a `RunRecord` that rerun and re-infer answers are read for. */
export interface RunRef {
  run_id: string;
}

/** Statuses of a run that can still be stopped. */
export const ACTIVE_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>(["queued", "running"]);
/** Statuses drawn as a failure mark. */
export const FAILED_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "failed",
  "killed",
  "lost",
]);
