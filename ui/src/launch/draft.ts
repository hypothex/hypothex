/**
 * The Launch dialog's form: its fields, the defaults taken from a template run, and the
 * checks that decide whether Launch is enabled (blockers) or only advised against (warnings).
 */
import type { RunRecord } from "../api/models";
import { shellJoin } from "../pages/components/format";
import { hasSeedSlot, splitCommand } from "./command";
import { type LaunchHost, type LaunchPlan, availability, freeGpus, gpuLimit, planLaunch, validSlurmTime } from "./plan";
import { MAX_SEED, nextSeeds, parseSeeds } from "./seeds";

export interface LaunchDraft {
  host: string | null;
  /** GPUs per run (per job on SLURM). */
  gpus: number;
  /** Wait for GPUs in the hx queue (SSH hosts only). */
  queue: boolean;
  seeds: string;
  command: string;
  hypothesis: string;
  /** SLURM fields; blank means the host's `SlurmDefaults` value (nothing is sent). */
  partition: string;
  account: string;
  time: string;
}

export const DEFAULT_DRAFT: LaunchDraft = {
  host: null,
  gpus: 1,
  queue: true,
  seeds: "1, 2, 3",
  command: "",
  hypothesis: "",
  partition: "",
  account: "",
  time: "",
};

/** Template params and vars sent with every launch, so `{config}`-style slots still fill. */
export interface Carry {
  params: Record<string, string>;
  vars: Record<string, string>;
}

export const NO_CARRY: Carry = { params: {}, vars: {} };

/**
 * The commit a launch from `template` pins (spec 8A.4): the template's commit when it had no
 * uncommitted changes. A dirty run's diff is not available here, and a bare commit would
 * drop it, so then nothing is pinned and the hub pins its own checkout's HEAD and diff.
 */
export function pinnedCommit(template: RunRecord | null): string | null {
  if (template === null || template.git.dirty) return null;
  return template.git.commit ?? null;
}

export interface LaunchDefaults {
  draft: Partial<LaunchDraft>;
  carry: Carry;
  templateEnvironment?: string;
  /** Why no seeds are proposed (incomplete history or exhausted higher seeds). */
  seedsNote?: string;
}

export const NO_SEED_WARNING = "no {seed} in the command: every seed runs the same command";
export const TIME_ERROR = "time: e.g. 30, 1:30:00 or 2-01:30:00";
export const SEED_HISTORY_CUT = "run history cut short: pick seeds no run of this config used";

/** The slot `hx run --config FILE` fills with the run's copy of FILE. */
export const CONFIG_SLOT = "{config}";
/**
 * A launch sends no config file, so `{config}` fills only from a `config` var: the template
 * run's `--config` copy stays in that run's folder.
 */
export const CONFIG_ERROR = "{config} has no value (a --config file is not sent); write the file's path there";

/** Characters an `#SBATCH` value may hold (the backend's `_SAFE_VALUE`, checked in `validate_defaults`). */
export const SLURM_VALUE = /^[A-Za-z0-9_.:+@\/,-]*$/;

/** The blocker for a partition or account the backend would refuse. */
export function slurmValueError(field: "partition" | "account"): string {
  return `${field}: use letters, digits and _ . : + @ / , - only`;
}

/**
 * Defaults from a template run (the best config's latest run): its command template, its
 * params and vars, and the next three seeds after every seed used by runs of the same config.
 * `complete` is false when `runs` is not every run of the task (`AllRuns.complete`): an
 * older run may hold any seed then, so none is proposed and `seedsNote` says why.
 */
export function launchDefaults(
  template: RunRecord | null,
  runs: readonly RunRecord[],
  complete = true,
): LaunchDefaults {
  if (template === null) return { draft: { seeds: nextSeeds([]).join(", ") }, carry: NO_CARRY };
  const argv = template.command_template.length > 0 ? template.command_template : template.command;
  const carry = { params: { ...template.params }, vars: { ...template.vars } };
  const request = template.gpus_requested === undefined ? {} : { gpus: template.gpus_requested };
  const templateEnvironment = template.environment_id;
  if (!complete) {
    return {
      draft: { command: shellJoin(argv), seeds: "", ...request },
      carry,
      templateEnvironment,
      seedsNote: SEED_HISTORY_CUT,
    };
  }
  const used = runs.filter((r) => r.config_hash === template.config_hash).map((r) => r.seed);
  used.push(template.seed);
  const seeds = nextSeeds(used);
  return {
    draft: { command: shellJoin(argv), seeds: seeds.join(", "), ...request },
    carry,
    templateEnvironment,
    ...(seeds.length === 0 ? { seedsNote: `no higher seeds available: choose unused seeds up to ${MAX_SEED}` } : {}),
  };
}

export interface DraftCheck {
  seeds: number[];
  /** Seeds not started yet by this dialog: the ones Launch sends, and the GPU plan counts. */
  pending: number[];
  argv: string[];
  plan: LaunchPlan | null;
  /** Reasons Launch is disabled, in field order; empty when it may launch. */
  blockers: string[];
  warnings: string[];
  seedsError: string | null;
  commandError: string | null;
  timeError: string | null;
  partitionError: string | null;
  accountError: string | null;
}

/**
 * Validate the form against the chosen host. `started` are the seeds this dialog launched
 * already: they are never sent again, so the GPU plan (and its blocker) counts only the rest.
 * `vars` are the template vars sent with the launch (`Carry.vars`).
 */
export function checkDraft(
  draft: LaunchDraft,
  host: LaunchHost | null,
  project: string,
  now: number = Date.now(),
  started: readonly number[] = [],
  vars: Readonly<Record<string, string>> = {},
): DraftCheck {
  const blockers: string[] = [];
  const warnings: string[] = [];
  if (host === null) {
    blockers.push("pick a host");
  } else {
    const av = availability(host, project, now);
    if (!av.ok) blockers.push(av.reason);
    if (host.state === "connected" && host.kind !== "slurm" && draft.gpus > gpuLimit(host)) {
      blockers.push(`${draft.gpus} GPUs requested; ${host.name} has ${gpuLimit(host)}`);
    }
  }
  const parsed = parseSeeds(draft.seeds);
  if (parsed.error !== null) blockers.push(`seeds: ${parsed.error}`);
  const split = splitCommand(draft.command);
  const noConfig = !("config" in vars) && split.argv.some((a) => a.includes(CONFIG_SLOT));
  const commandError = split.error ?? (split.argv.length === 0 ? "empty" : noConfig ? CONFIG_ERROR : null);
  if (commandError !== null) blockers.push(`command: ${commandError}`);
  if (!draft.hypothesis.trim()) blockers.push("hypothesis required");
  const slurm = host?.kind === "slurm";
  const timeError = slurm && draft.time.trim() !== "" && !validSlurmTime(draft.time) ? TIME_ERROR : null;
  if (timeError !== null) blockers.push(timeError);
  const partitionError = slurm && !SLURM_VALUE.test(draft.partition.trim()) ? slurmValueError("partition") : null;
  if (partitionError !== null) blockers.push(partitionError);
  const accountError = slurm && !SLURM_VALUE.test(draft.account.trim()) ? slurmValueError("account") : null;
  if (accountError !== null) blockers.push(accountError);
  const pending = parsed.seeds.filter((seed) => !started.includes(seed));
  const plan = host === null ? null : planLaunch(host, draft.gpus, pending.length, draft.queue);
  if (host !== null && plan !== null && plan.blocked > 0) {
    const free = freeGpus(host).length;
    blockers.push(
      host.kind === "ssh"
        ? `${plan.blocked} won't start: ${free} GPU free; turn on Queue`
        : `${plan.blocked} won't start: ${free} GPU free on ${host.name}`,
    );
  }
  if (parsed.seeds.length > 1 && split.argv.length > 0 && !hasSeedSlot(split.argv)) {
    warnings.push(NO_SEED_WARNING);
  }
  const op = split.operators[0];
  if (op !== undefined) warnings.push(`${op} is passed to the program as text; use sh -c '…' for shell syntax`);
  return {
    seeds: parsed.seeds,
    pending,
    argv: split.argv,
    plan,
    blockers,
    warnings,
    seedsError: parsed.error,
    commandError,
    timeError,
    partitionError,
    accountError,
  };
}
