/**
 * `/s/$project/$id`: a sweep link. A sweep of a task opens that task's Sweeps tab
 * (`/t/$project/$task?tab=sweeps&sweep=$id`, history replaced); a sweep without a task, or
 * one that fails to load, is shown in place.
 */
import { useRouter } from "@tanstack/react-router";
import { type ReactElement, useEffect } from "react";
import { useSweep } from "../api/queries";
import { hrefs } from "../pages/components/links";
import { Loading } from "../pages/components/QueryState";
import { SweepDetail } from "./SweepDetail";
import "./task.css";

export function SweepRedirect({ project, sweepId }: { project: string; sweepId: string }): ReactElement {
  const summary = useSweep(project, sweepId);
  const router = useRouter({ warn: false }) as unknown as { history: { replace: (href: string) => void } } | null | undefined;
  const task = summary.data?.spec.task ?? null;
  useEffect(() => {
    if (task === null) return;
    const href = hrefs.taskSweep(project, task, sweepId);
    if (router) router.history.replace(href);
    else window.location.replace(href);
  }, [project, task, sweepId, router]);
  if (task === null && (summary.data || summary.error)) {
    return (
      <div className="task-page">
        <SweepDetail project={project} sweepId={sweepId} />
      </div>
    );
  }
  return <Loading />;
}
