/**
 * "Rerun sweep" (contract section 4): the Launch dialog, prefilled from the sweep's best
 * cell. The template is the cell's latest run: its command template (with the `{param}`
 * and `{seed}` slots), its params and vars (sent with every seed, so the slots fill), its
 * GPUs per run, the sweep's host, and the next seeds after every seed that config used.
 */
import { type ReactElement, useRef } from "react";
import type { RunRecord, RunsQuery, SweepSpec } from "../../api/models";
import { useAllRuns, useProjects } from "../../api/queries";
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
  /** Why no seeds are proposed (`SEED_HISTORY_CUT`); absent when they are. */
  seedsNote?: string;
}

/**
 * `GET /api/v1/runs` query for the seed history: every run of the sweep's task (of the
 * project for a sweep without a task), archived included. A rerun's runs carry no sweep
 * tag, so the sweep's own runs do not show the seeds an earlier rerun used.
 */
export function rerunHistoryQuery(project: string, task: string | null): Omit<RunsQuery, "limit"> {
  return task === null ? { project, archived: true } : { project, task, archived: true };
}

/**
 * The best cell's latest run (else the sweep's latest run) and the dialog defaults it gives.
 * `history` is every other run that may hold a seed of that config (`rerunHistoryQuery`);
 * `complete` is false when that list is cut (`AllRuns.complete`): then no seed is proposed.
 */
export function rerunDefaults(
  spec: SweepSpec,
  best: SweepCellRow | null,
  runs: readonly RunRecord[],
  history: readonly RunRecord[] = [],
  complete = true,
): RerunDefaults {
  const pool = best ? runs.filter((r) => best.run_ids.includes(r.run_id)) : [...runs];
  const template = [...pool].sort((a, b) => parseTime(b.created_at) - parseTime(a.created_at))[0] ?? null;
  const defaults = launchDefaults(template, [...runs, ...history], complete);
  // a CPU template (0 GPUs) stays a CPU run; a run with no field (phase 1) takes the default
  const gpus = template?.gpus_requested;
  return {
    template,
    initial: { ...defaults.draft, host: spec.host, ...(gpus !== undefined ? { gpus } : {}) },
    carry: defaults.carry,
    commit: pinnedCommit(template),
    ...(defaults.seedsNote !== undefined ? { seedsNote: defaults.seedsNote } : {}),
  };
}

export interface SweepRerunProps {
  project: string;
  spec: SweepSpec;
  best: SweepCellRow | null;
  /** The sweep's runs, in launch order; undefined while they load. */
  runs: readonly RunRecord[] | undefined;
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

interface Opened {
  repo: string;
  defaults: RerunDefaults;
}

/**
 * Loads the project's repo path on the hub, the sweep's runs and the seed history, then
 * shows the Launch dialog.
 *
 * The defaults freeze when everything has loaded (a history refetch included: each launch
 * invalidates runs, and a reopened dialog must see the seeds the last one started). Run
 * events refetch the sweep while it is open, and a new best cell must not change the
 * params, vars or commit that Launch sends (the dialog reads `initial` once, so the seeds
 * shown would no longer match them); a failed refetch must not swap the dialog out either.
 */
export function SweepRerun({ project, spec, best, runs, onClose, onLaunched }: SweepRerunProps): ReactElement {
  const projects = useProjects();
  const history = useAllRuns(rerunHistoryQuery(project, spec.task));
  const opened = useRef<Opened | null>(null);
  if (opened.current === null) {
    const error = projects.error ?? history.error;
    if (error) return <ErrorBox error={error} />;
    if (projects.data === undefined || history.data === undefined || history.isFetching || runs === undefined) {
      return <Loading />;
    }
    const repo = projects.data.find((p) => p.project === project)?.repo;
    if (repo === undefined) return <ErrorBox error={new Error(`no repo for ${project} on the hub`)} />;
    opened.current = {
      repo,
      defaults: rerunDefaults(spec, best, runs, history.data.runs, history.data.complete),
    };
  }
  const { repo, defaults: d } = opened.current;
  return (
    <LaunchDialog
      project={project}
      task={spec.task}
      repo={repo}
      commit={d.commit}
      title="Rerun sweep"
      initial={d.initial}
      carry={d.carry}
      seedsNote={d.seedsNote}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  );
}
