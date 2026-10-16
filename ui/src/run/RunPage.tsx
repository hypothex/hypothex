/**
 * Run page (spec 4.3): header with the run's identity colour, name, status, actions and
 * tabs; the tab's main column; the properties sidebar (R4). Tabs live in `?tab=`; an old
 * `?log=` link opens the Logs tab on that stream; `?example=` picks a trace.
 */
import type { CSSProperties } from "react";
import { ApiError } from "../api/client";
import { useLostReason } from "../api/lostReasons";
import { HOSTS_REFETCH_MS, useHosts, useHubEnvironment, useRun, useTask, useTaskKind, useTaskRuns } from "../api/queries";
import { useNow } from "../pages/components/HostsPanel";
import { AppLink, hrefs } from "../pages/components/links";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { runHostRow, runPhase } from "../pages/components/remote";
import { RunHeader } from "./RunHeader";
import { type RunContext, type RunTab, asLogStream, compareTarget, runIdentity, shownTab } from "./runContext";
import { runTitle } from "./RunName";
import "./run.css";

/** Clock tick of an unfinished run: its elapsed times move even when a poll returns the same data. */
export const RUN_CLOCK_MS = 10_000;

export interface RunPageProps {
  runId: string;
  tab?: string;
  log?: string;
  example?: string;
  clockMs?: number;
}

export function RunPage({ runId, tab, log, example, clockMs = RUN_CLOCK_MS }: RunPageProps) {
  const run = useRun(runId);
  const lostWhy = useLostReason(runId);
  const record = run.data?.record;
  const project = record?.project ?? "";
  const task = record?.task ?? "";
  const hasTask = task !== "";
  const taskRuns = useTaskRuns(project, task, { archived: record?.archived === true, enabled: hasTask });
  const kind = useTaskKind(project, task, { enabled: hasTask });
  const taskDetail = useTask(project, task, { enabled: hasTask });
  // an unserved environment needs host lookup even without a connection state
  const remote = (run.data?.host_state ?? null) !== null || run.data?.served === false;
  const hosts = useHosts(HOSTS_REFETCH_MS, remote);
  const hubEnv = useHubEnvironment({ enabled: Boolean(record?.sweep_id) });
  const now = useNow(clockMs, record !== undefined && record.ended_at === null);

  if (run.error) {
    const missing = run.error instanceof ApiError && run.error.status === 404;
    return (
      <div className="run-page">
        <header className="rhead">
          {missing ? (
            <>
              <h1>Not found</h1>
              <p className="rhyp">
                <AppLink href={hrefs.overview()}>Home</AppLink>
              </p>
            </>
          ) : null}
          <ErrorBox error={run.error} />
        </header>
      </div>
    );
  }
  if (!run.data || !record) {
    return (
      <div className="run-page">
        <Loading />
      </div>
    );
  }
  const detail = run.data;
  const data = taskRuns.data ?? null;
  const identity = runIdentity(data, runId);
  const hubEnvId = hubEnv.data?.environment_id;
  const other = hasTask ? compareTarget(data, runId) : null;
  const ctx: RunContext = {
    runId,
    detail,
    record,
    phase: runPhase(detail),
    host: runHostRow(detail, hosts.data),
    hostsLoaded: hosts.data !== undefined,
    remote,
    now,
    lostWhy,
    hubEnvId: typeof hubEnvId === "string" ? hubEnvId : null,
    taskRuns: data,
    identity,
    title: runTitle(identity.run, record),
    kind: kind.data ?? null,
    kindError: kind.error ?? null,
    inferStage: !hasTask ? false : taskDetail.isSuccess ? Object.hasOwn(taskDetail.data.stages, "infer") : undefined,
    compareHref: !hasTask ? undefined : other ? hrefs.examples(other, runId) : null,
    example,
    log: asLogStream(log),
  };
  const current = shownTab(tab, log);
  return (
    <div className="run-page" style={{ "--rc": identity.color } as CSSProperties}>
      <RunHeader ctx={ctx} tab={current} />
      <div className="rbody">
        <RunTabBody ctx={ctx} tab={current} />
      </div>
    </div>
  );
}

/** The main column of one tab; R3 and R5 fill in the tabs. */
function RunTabBody({ ctx, tab }: { ctx: RunContext; tab: RunTab }) {
  return <div className="rmain" data-tab={tab} data-run={ctx.runId} />;
}
