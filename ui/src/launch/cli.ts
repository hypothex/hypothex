/**
 * "Copy as CLI": the exact `hx launch` lines the dialog would run, one per seed, quoted for
 * `sh`/`bash`/`zsh`. `{seed}` is always quoted (a shell can drop or expand a bare one).
 */
import { type LaunchSpec, type SlurmFields, slurmBody } from "./plan";

const CLI_SAFE = /^[A-Za-z0-9_\-+=/.,:@%]+$/;

/** Quote one argument for a POSIX shell; plain words stay bare. */
export function cliQuote(arg: string): string {
  if (arg === "") return "''";
  return CLI_SAFE.test(arg) ? arg : `'${arg.replace(/'/g, `'"'"'`)}'`;
}

/** One `hx launch` command for one seed. */
export function launchCliLine(spec: LaunchSpec, seed: number): string {
  const parts = ["hx", "launch", "--repo", cliQuote(spec.repo)];
  if (spec.task !== null) parts.push("-t", cliQuote(spec.task));
  if (spec.host.kind !== "hub") parts.push("--host", cliQuote(spec.host.name));
  if (spec.gpus > 0) parts.push("--gpus", String(spec.gpus));
  if (spec.host.kind === "ssh" && spec.queue) parts.push("--queue");
  if (spec.host.kind === "slurm" && spec.slurm !== null) {
    parts.push(...slurmFlags(spec.slurm, spec.gpus, ["partition", "time", "account"]));
  }
  parts.push("--seed", String(seed));
  for (const [key, value] of Object.entries(spec.params)) parts.push("--param", cliQuote(`${key}=${value}`));
  for (const [key, value] of Object.entries(spec.vars)) parts.push("--var", cliQuote(`${key}=${value}`));
  parts.push("-H", cliQuote(spec.hypothesis.trim()), "--", ...spec.argv.map(cliQuote));
  return parts.join(" ");
}

/**
 * One `hx launch` line per seed, newline-separated. `hx launch` has no commit flag, so a
 * pinned commit (Rerun sweep) is named in a first comment line, harmless when pasted.
 */
export function launchCli(spec: LaunchSpec, seeds: readonly number[]): string {
  const lines = seeds.map((seed) => launchCliLine(spec, seed));
  if (spec.commit !== null) lines.unshift(`# code: commit ${spec.commit}; hx launch runs the checkout as it is`);
  return lines.join("\n");
}

/** The sbatch flags the dialog sets for a SLURM run (spec 8A.5); the host's defaults fill the rest. */
export function sbatchLine(slurm: SlurmFields, gpus: number): string {
  return ["sbatch", ...slurmFlags(slurm, gpus, ["partition", "time", "gpus", "account"])].join(" ");
}

type SlurmFlag = "partition" | "time" | "account" | "gpus";

/**
 * `--key value` for each key, in `keys` order, that the API body (`slurmBody`) sends, so the
 * CLI lines always match what the dialog sends: a blank field (the host's default) is left
 * out. `--gpus 0` is left out too, as `render_sbatch` leaves it out of the script.
 */
function slurmFlags(slurm: SlurmFields, gpus: number, keys: readonly SlurmFlag[]): string[] {
  const body = slurmBody(slurm, gpus);
  return keys.flatMap((key) => {
    const value = body[key];
    if (value === undefined || value === null || value === 0) return [];
    return [`--${key}`, typeof value === "number" ? String(value) : cliQuote(value)];
  });
}
