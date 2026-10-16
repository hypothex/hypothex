/**
 * Sweeps tab (spec 4.2): the task's sweeps (those its runs belong to, newest first, plus a
 * sweep named by `?sweep=` that has no task run yet) and the selected sweep's detail.
 */
import type { ReactElement } from "react";
import type { TaskRuns } from "../api/models";
import { useProjectSweeps } from "../api/queries";
import { EmptyState } from "../chrome/EmptyState";
import { fmtScore } from "../pages/components/format";
import { paramsText } from "../pages/components/SweepModel";
import { SweepDetail } from "./SweepDetail";
import { taskSweepIds } from "./sweepMath";

export interface SweepsTabProps {
  project: string;
  data: TaskRuns;
  sweepId: string | null;
  onSelect: (id: string) => void;
  now?: number;
}

export function SweepsTab({ project, data, sweepId, onSelect, now }: SweepsTabProps): ReactElement {
  const list = useProjectSweeps(project);
  const own = taskSweepIds(data);
  const ids = sweepId !== null && !own.includes(sweepId) ? [sweepId, ...own] : own;
  const current = sweepId ?? ids[0] ?? null;
  if (current === null) return <EmptyState title="No sweeps" />;
  return (
    <div className="sweeps">
      <nav className="sweep-list" aria-label="Sweeps">
        {ids.map((id) => {
          const info = list.data?.find((s) => s.id === id);
          return (
            <button key={id} type="button" className={id === current ? "on" : undefined} aria-current={id === current ? "true" : undefined} onClick={() => onSelect(id)}>
              <b>{id}</b>
              <span className="muted">{info ? `${info.n_runs} runs` : ""}</span>
              {info?.best && info.best.mean !== null ? (
                <span className="best-line">{`${paramsText(info.best.params, Object.keys(info.best.params))} ${fmtScore(info.best.mean)}`}</span>
              ) : null}
            </button>
          );
        })}
      </nav>
      <SweepDetail key={current} project={project} sweepId={current} data={data} now={now} />
    </div>
  );
}
