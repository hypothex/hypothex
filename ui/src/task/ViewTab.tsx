/**
 * A saved (non-preset) view as a task tab (`?tab=view:<name>`): its panels in panel
 * chrome, with the v4 toolbar: Metric (primary override), Seeds / Repeats (leaderboard
 * seed dots), panel count and Edit. While the next query loads, the previous panels are
 * not drawn under the new specs.
 */
import { type ReactElement, useState } from "react";
import type { Leaderboard, ViewInfo } from "../api/models";
import { useView, useViewQuery } from "../api/queries";
import { AppLink, hrefs } from "../pages/components/links";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { SelectedRun } from "../pages/components/SelectedRun";
import { applyOverrides, authoredSeeds, leaderboardPanels, metricOptions } from "./viewOverrides";
import { ViewPanels } from "./ViewPanels";

export interface ViewTabProps {
  project: string;
  task: string;
  name: string;
  board: Leaderboard | undefined;
  info: ViewInfo | undefined;
}

export function ViewTab({ project, task, name, board, info }: ViewTabProps): ReactElement {
  const [primary, setPrimary] = useState<string | undefined>(undefined);
  const [seeds, setSeeds] = useState<boolean | undefined>(undefined);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const detail = useView(project, task, name);
  const view = detail.data?.view;
  const customized = primary !== undefined || seeds !== undefined;
  const effective = view ? applyOverrides(view, { primary, seeds }) : undefined;
  const panels = useViewQuery(project, task, customized ? (effective ? { view: effective } : null) : { name });
  const origin = (info ?? detail.data?.info)?.origin;
  const error = detail.error ?? panels.error;
  const ready = panels.data !== undefined && !panels.isPlaceholderData && !detail.isPending;
  const authored = view ? authoredSeeds(view) : true;
  const seedWord = board?.kind === "system_bench" ? "Repeats" : "Seeds";
  const count = view?.panels?.length ?? 0;
  return (
    <div className="view-tab panels">
      <div className="ptools">
        {board ? (
          <label>
            Metric
            <select
              className="ctl"
              aria-label="Metric"
              value={primary ?? board.primary}
              title="Ranking metric and primary summaries; authored plot axes remain unchanged"
              onChange={(e) => setPrimary(e.target.value === board.primary ? undefined : e.target.value)}
            >
              {metricOptions(board).map((ref) => (
                <option key={ref} value={ref} title={`${ref} @ ${board.metric_versions[ref.split("/")[0] ?? ""]}`}>
                  {ref}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {view && leaderboardPanels(view).length > 0 ? (
          <label title="Show individual seed or repeat dots on leaderboard plots">
            <input
              type="checkbox"
              aria-label={seedWord}
              checked={seeds ?? authored}
              onChange={(e) => setSeeds(e.target.checked === authored ? undefined : e.target.checked)}
            />
            {seedWord}
          </label>
        ) : null}
        <span className="sp" />
        {view ? <span className="muted">{`${count} panel${count === 1 ? "" : "s"}`}</span> : null}
        {origin !== undefined && origin !== "preset" ? (
          <AppLink className="btn sm" href={hrefs.edit(project, task, name)}>
            Edit
          </AppLink>
        ) : null}
      </div>
      {error ? (
        <ErrorBox error={error} />
      ) : ready && panels.data ? (
        <ViewPanels
          results={panels.data.panels}
          specs={customized ? effective?.panels : view?.panels}
          kind={board?.kind}
          onSelectRun={setSelectedRun}
        />
      ) : (
        <Loading />
      )}
      {selectedRun ? <SelectedRun runId={selectedRun} onClose={() => setSelectedRun(null)} /> : null}
    </div>
  );
}
