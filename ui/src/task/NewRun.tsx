/**
 * "+ New run" (spec 8A.8): the Launch dialog prefilled from the best config's latest run
 * (its command template, params and vars, and the next unused seeds of that config). What
 * it opened with is kept until the dialog closes: a refetch (each launch invalidates runs)
 * or a failed refetch must not swap the dialog for a spinner or an error.
 */
import { useQuery } from "@tanstack/react-query";
import { Fragment, type ReactElement, useRef } from "react";
import { api } from "../api/client";
import type { RunRecord } from "../api/models";
import { queryKeys, useAllRuns, useTask } from "../api/queries";
import { type LaunchDefaults, launchDefaults } from "../launch/draft";
import { LaunchDialog } from "../launch/LaunchDialog";
import { shortId } from "../pages/components/format";
import { AppLink, hrefs } from "../pages/components/links";
import { OpeningDialog } from "../pages/components/OpeningDialog";

export interface LaunchedRuns {
  host: string;
  records: RunRecord[];
}

export interface NewRunProps {
  project: string;
  task: string;
  templateRunId: string | null;
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

interface Opened {
  repo: string;
  defaults: LaunchDefaults;
}

/**
 * Loads the repo path, the template run and every run of the task, archived included (an
 * older or archived run may hold a seed), then shows the dialog.
 */
export function NewRun({ project, task, templateRunId, onClose, onLaunched }: NewRunProps): ReactElement {
  const detail = useTask(project, task);
  const runs = useAllRuns({ project, task, archived: true });
  const template = useQuery({
    queryKey: queryKeys.run(templateRunId ?? ""),
    queryFn: ({ signal }) => api.run(templateRunId ?? "", signal),
    enabled: templateRunId !== null,
  });
  const opened = useRef<Opened | null>(null);
  if (opened.current === null) {
    // A failed runs read would propose seeds that already exist; a failed template read
    // would open a blank dialog without saying so. Both stop here instead.
    const error = detail.error ?? runs.error ?? template.error;
    if (error) {
      return (
        <OpeningDialog
          title="New run"
          error={error}
          onClose={onClose}
          onRetry={() => {
            void detail.refetch();
            void runs.refetch();
            if (templateRunId !== null) void template.refetch();
          }}
        />
      );
    }
    // a refetch in flight too: a cached list may predate runs started since (by anyone)
    if (detail.data === undefined || runs.data === undefined || runs.isFetching || (templateRunId !== null && template.isPending)) {
      return <OpeningDialog title="New run" onClose={onClose} />;
    }
    opened.current = {
      repo: detail.data.repo,
      defaults: launchDefaults(template.data?.record ?? null, runs.data.runs, runs.data.complete),
    };
  }
  const { repo, defaults } = opened.current;
  return (
    <LaunchDialog
      project={project}
      task={task}
      repo={repo}
      initial={defaults.draft}
      templateEnvironment={defaults.templateEnvironment}
      carry={defaults.carry}
      seedsNote={defaults.seedsNote}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  );
}

/** `Launched 3 on gpu1, 2 queued: f2c8 93e7 c2b9`, each id a link to its run. */
export function LaunchedLine({ launched }: { launched: LaunchedRuns }): ReactElement {
  const queued = launched.records.filter((r) => r.status === "queued").length;
  return (
    <p className="small launched" role="status">
      Launched {launched.records.length} on {launched.host}
      {queued > 0 ? `, ${queued} queued` : ""}:{" "}
      {launched.records.map((r, i) => (
        <Fragment key={r.run_id}>
          {i > 0 ? " " : ""}
          <AppLink href={hrefs.run(r.run_id)}>{shortId(r.run_id)}</AppLink>
        </Fragment>
      ))}
    </p>
  );
}
