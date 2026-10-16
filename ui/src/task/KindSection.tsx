/**
 * The task kind's preset panels and extras, one collapsible section of the Charts tab
 * (spec 4.2 "The task kind's preset panels ... render in the same panel chrome"). The
 * preset's leaderboard and per-config curves are left out: the Scores and Step metrics
 * sections draw them. Extras keep their v4 behaviour: training run and checkpoint tables,
 * iteration example changes, benchmark raw samples scoped to the inline-selected run.
 * The section uses the one-column grid: the preset panels bring their own `PanelGrid`.
 */
import { type ReactElement, type ReactNode, useState } from "react";
import type { Leaderboard, PanelSpec, TaskKind, ViewSpec } from "../api/models";
import { useView, useViewQuery } from "../api/queries";
import { Panel } from "../chrome/Panel";
import { PanelSection } from "../chrome/PanelSection";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { SelectedRun } from "../pages/components/SelectedRun";
import { AgentIterationFlips, SystemRawSamples } from "../pages/components/TaskInsights";
import { TrainingCheckpoints, TrainingRuns } from "../pages/components/TrainingDetails";
import { ViewPanels } from "./ViewPanels";

export const KIND_TITLE: Record<TaskKind, string> = {
  generic: "Summary",
  training: "Training",
  agent_eval: "Agent eval",
  agent_iteration: "Iterations",
  system_bench: "Benchmark",
};

/** Preset panels this section draws: all but leaderboards and `group_by: group` curves. */
export function presetPanels(view: ViewSpec): PanelSpec[] {
  return (view.panels ?? []).filter(
    (p) => p.type !== "leaderboard" && !(p.type === "curves" && (p.data?.group_by ?? "group") === "group"),
  );
}

export interface KindSectionProps {
  project: string;
  task: string;
  kind: TaskKind;
  board: Leaderboard | undefined;
}

export function KindSection({ project, task, kind, board }: KindSectionProps): ReactElement {
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const preset = useView(project, task, "overview");
  const panels = preset.data ? presetPanels(preset.data.view) : [];
  const body = preset.data && panels.length > 0 ? { view: { ...preset.data.view, panels } } : null;
  const results = useViewQuery(project, task, body);
  const select = (runId: string): void => setSelectedRun(runId);
  const extras: { title: string; node: ReactNode }[] =
    kind === "training"
      ? [
          { title: "Training runs", node: <TrainingRuns project={project} task={task} onSelectRun={select} /> },
          { title: "Checkpoint metrics", node: <TrainingCheckpoints project={project} task={task} onSelectRun={select} /> },
        ]
      : kind === "agent_iteration"
        ? [{ title: "Example changes", node: <AgentIterationFlips project={project} task={task} board={board} /> }]
        : kind === "system_bench"
          ? [{ title: "Raw samples", node: <SystemRawSamples project={project} task={task} selectedRunId={selectedRun ?? undefined} /> }]
          : [];
  return (
    <PanelSection title={KIND_TITLE[kind]} count={panels.length + extras.length} storageKey={`${project}/${task}`} grid="wide">
      {preset.error ? (
        <ErrorBox error={preset.error} />
      ) : results.error ? (
        <ErrorBox error={results.error} />
      ) : body === null ? null : results.data && !results.isPlaceholderData ? (
        <ViewPanels results={results.data.panels} specs={panels} kind={kind} onSelectRun={select} />
      ) : (
        <Loading />
      )}
      {extras.map((x) => (
        <Panel key={x.title} title={x.title}>
          {x.node}
        </Panel>
      ))}
      {selectedRun ? <SelectedRun runId={selectedRun} onClose={() => setSelectedRun(null)} /> : null}
    </PanelSection>
  );
}
