/** Charts tab (spec 4.2): the runs sidebar and the panel area. T4 adds the toolbar and sections. */
import type { ReactElement } from "react";
import type { Leaderboard, TaskRuns } from "../api/models";
import { KindSection } from "./KindSection";
import { RunsSidebar } from "./RunsSidebar";
import type { Selection } from "./useRunSelection";

export interface ChartsTabProps {
  project: string;
  task: string;
  data: TaskRuns;
  board: Leaderboard | undefined;
  selection: Selection;
  onSelection: (patch: Partial<Selection>) => void;
  onOpenRun: (runId: string) => void;
}

export function ChartsTab({ project, task, data, board, selection, onSelection, onOpenRun }: ChartsTabProps): ReactElement {
  return (
    <div className="ws">
      <RunsSidebar data={data} selection={selection} onChange={onSelection} onOpen={onOpenRun} />
      <div className="panels">
        <KindSection project={project} task={task} kind={data.kind} board={board} />
      </div>
    </div>
  );
}
