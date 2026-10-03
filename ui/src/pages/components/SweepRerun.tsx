/**
 * "Rerun sweep" (contract section 4): the Launch dialog, prefilled from the sweep's best
 * cell. The template is the cell's latest run: its command template (with the `{param}`
 * and `{seed}` slots), its params and vars (sent with every seed, so the slots fill), its
 * GPUs per run, the sweep's host, and the next seeds after every seed that config used.
 */
import { type ReactElement, useState } from "react";
import type { RunRecord, SweepSpec } from "../../api/models";
import { useProjects } from "../../api/queries";
import { type Carry, type LaunchDraft, launchDefaults, pinnedCommit } from "../../launch/draft";
import { LaunchDialog } from "../../launch/LaunchDialog";
import { parseTime } from "./format";
import { ErrorBox, Loading } from "./QueryState";
import type { SweepCellRow } from "./SweepModel";

export interface RerunDefaults {
  /** The run the dialog copies; null when the sweep has no run yet. */
  template: RunRecord | null;
  initial: Partial<LaunchDraft>;
  carry: Carry;
  /** The template's commit when it ran clean (`pinnedCommit`); null: the hub pins its own. */
  commit: string | null;
}

/** The best cell's latest run (else the sweep's latest run) and the dialog defaults it gives. */
export function rerunDefaults(spec: SweepSpec, best: SweepCellRow | null, runs: readonly RunRecord[]): RerunDefaults {
  const pool = best ? runs.filter((r) => best.run_ids.includes(r.run_id)) : [...runs];
  const template = [...pool].sort((a, b) => parseTime(b.created_at) - parseTime(a.created_at))[0] ?? null;
  const defaults = launchDefaults(template, runs);
  const gpus = template?.gpus_requested ?? 0;
  return {
    template,
    initial: { ...defaults.draft, host: spec.host, ...(gpus > 0 ? { gpus } : {}) },
    carry: defaults.carry,
    commit: pinnedCommit(template),
  };
}

export interface SweepRerunProps {
  project: string;
  spec: SweepSpec;
  best: SweepCellRow | null;
  /** The sweep's runs, in launch order. */
  runs: readonly RunRecord[];
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

/**
 * Loads the project's repo path on the hub, then shows the Launch dialog.
 *
 * The defaults freeze when the dialog opens: run events refetch the sweep while it is
 * open, and a new best cell must not change the params, vars or commit that Launch sends
 * (the dialog reads `initial` once, so the seeds shown would no longer match them).
 */
export function SweepRerun({ project, spec, best, runs, onClose, onLaunched }: SweepRerunProps): ReactElement {
  const [d] = useState(() => rerunDefaults(spec, best, runs));
  const projects = useProjects();
  if (projects.error) return <ErrorBox error={projects.error} />;
  if (projects.data === undefined) return <Loading />;
  const repo = projects.data.find((p) => p.project === project)?.repo;
  if (repo === undefined) return <ErrorBox error={new Error(`no repo for ${project} on the hub`)} />;
  return (
    <LaunchDialog
      project={project}
      task={spec.task}
      repo={repo}
      commit={d.commit}
      title="Rerun sweep"
      initial={d.initial}
      carry={d.carry}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  );
}
