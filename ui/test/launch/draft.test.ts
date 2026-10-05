import { describe, expect, test } from "bun:test";

import {
  DEFAULT_DRAFT,
  type LaunchDraft,
  CONFIG_ERROR,
  NO_SEED_WARNING,
  SEED_HISTORY_CUT,
  TIME_ERROR,
  checkDraft,
  launchDefaults,
  pinnedCommit,
  slurmValueError,
} from "../../src/launch/draft";
import { toLaunchHosts } from "../../src/launch/plan";
import { makeRecord } from "../pages/fixtures";
import { CMD, GPU1, PROJECT, gpu, launchHost } from "./fixtures";

const G1 = toLaunchHosts([GPU1], { gpus: [], queue: 0 })[1] ?? launchHost();
const OK: LaunchDraft = {
  ...DEFAULT_DRAFT,
  host: "gpu1",
  seeds: "4, 5, 6",
  command: CMD,
  hypothesis: "beam 10 holds",
};

describe("launchDefaults", () => {
  test("explains exhausted higher seeds without wrapping or proposing invalid values", () => {
    const defaults = launchDefaults(makeRecord({ seed: 2147483647 }), []);
    expect(defaults.draft.seeds).toBe("");
    expect(defaults.seedsNote).toBe("no higher seeds available: choose unused seeds up to 2147483647");
  });

  test("no template: seeds 1, 2, 3 and nothing carried", () => {
    expect(launchDefaults(null, [])).toEqual({
      draft: { seeds: "1, 2, 3" },
      carry: { params: {}, vars: {} },
    });
  });

  test("the template's command, its params and vars, and the next unused seeds of its config", () => {
    const template = makeRecord({
      run_id: "r3",
      command_template: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
      seed: 3,
      config_hash: "sha256:aaaa",
      params: { lr: "3e-4" },
      vars: { config: "configs/aug.yaml" },
    });
    const runs = [
      makeRecord({ run_id: "r1", seed: 1, config_hash: "sha256:aaaa" }),
      makeRecord({ run_id: "r2", seed: 2, config_hash: "sha256:aaaa" }),
      makeRecord({ run_id: "r9", seed: 9, config_hash: "sha256:bbbb" }),
    ];
    expect(launchDefaults(template, runs)).toEqual({
      draft: { command: "python train.py --lr 3e-4 --seed {seed}", seeds: "4, 5, 6" },
      templateEnvironment: "env-5c1e",
      carry: { params: { lr: "3e-4" }, vars: { config: "configs/aug.yaml" } },
    });
  });

  test("a cut run history proposes no seeds: an older run may hold any of them", () => {
    const template = makeRecord({ run_id: "r3", seed: 3, config_hash: "sha256:aaaa" });
    const defaults = launchDefaults(template, [], false);
    expect(defaults.draft.seeds).toBe("");
    expect(defaults.seedsNote).toBe(SEED_HISTORY_CUT);
    expect(launchDefaults(template, [], true).seedsNote).toBeUndefined();
  });

  test("falls back to the rendered command when the template is empty", () => {
    const template = makeRecord({ command_template: [], command: ["python", "x.py", "--seed=3"], seed: null });
    expect(launchDefaults(template, []).draft).toEqual({ command: "python x.py --seed=3", seeds: "1, 2, 3" });
  });

  test("pinnedCommit: the template's commit when it was clean, else none (the hub pins its own)", () => {
    const clean = makeRecord();
    expect(pinnedCommit(clean)).toBe("8f4cac43877b75953f18ff1daf7e6fc54a5d8f37");
    // a dirty run's diff is not available to the dialog: pinning the bare commit would drop it
    expect(pinnedCommit(makeRecord({ git: { ...clean.git, dirty: true } }))).toBeNull();
    expect(pinnedCommit(makeRecord({ git: { ...clean.git, commit: null } }))).toBeNull();
    expect(pinnedCommit(null)).toBeNull();
  });
});

describe("checkDraft", () => {
  test("a complete draft has no blockers", () => {
    const c = checkDraft(OK, G1, PROJECT);
    expect(c.blockers).toEqual([]);
    expect(c.warnings).toEqual([]);
    expect(c.seeds).toEqual([4, 5, 6]);
    expect(c.argv).toEqual(["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"]);
    expect(c.plan).toEqual({ now: 1, queued: 2, blocked: 0, cvd: [5], firstPos: 4 });
  });

  test("blockers come in field order", () => {
    const c = checkDraft({ ...OK, seeds: "x", command: "python 'oops", hypothesis: "  " }, null, PROJECT);
    expect(c.blockers).toEqual([
      "pick a host",
      "seeds: bad seed x",
      "command: unclosed ' quote",
      "hypothesis required",
    ]);
    expect(c.seedsError).toBe("bad seed x");
    expect(c.commandError).toBe("unclosed ' quote");
    expect(c.plan).toBeNull();
  });

  test("an empty command is a blocker", () => {
    expect(checkDraft({ ...OK, command: "   " }, G1, PROJECT).blockers).toEqual(["command: empty"]);
  });

  test("a host that cannot take the run blocks with its reason", () => {
    expect(checkDraft(OK, { ...G1, projects: [] }, PROJECT).blockers).toEqual([
      "no path for rxn-forward on gpu1: hx hosts map rxn-forward gpu1 <path>",
    ]);
  });

  test("a SLURM host needs a valid --time, or none (the host's default)", () => {
    const slurm = launchHost({ name: "mccleary", kind: "slurm" });
    const bad = checkDraft({ ...OK, host: "mccleary", time: "8h" }, slurm, PROJECT);
    expect(bad.blockers).toEqual([TIME_ERROR]);
    expect(bad.timeError).toBe(TIME_ERROR);
    expect(checkDraft({ ...OK, host: "mccleary", time: "08:00:00" }, slurm, PROJECT).blockers).toEqual([]);
    expect(DEFAULT_DRAFT.time).toBe("");
    expect(checkDraft({ ...OK, host: "mccleary" }, slurm, PROJECT).blockers).toEqual([]);
  });

  test("a SLURM partition or account with spaces or shell characters blocks Launch", () => {
    const slurm = launchHost({ name: "mccleary", kind: "slurm" });
    const c = checkDraft({ ...OK, host: "mccleary", partition: "gpu a100", account: "lab;rm" }, slurm, PROJECT);
    expect(c.blockers).toEqual([slurmValueError("partition"), slurmValueError("account")]);
    expect(slurmValueError("partition")).toBe("partition: use letters, digits and _ . : + @ / , - only");
    expect([c.partitionError, c.accountError]).toEqual([slurmValueError("partition"), slurmValueError("account")]);
    const ok = checkDraft({ ...OK, host: "mccleary", partition: "gpu,scavenge", account: "pi_lab" }, slurm, PROJECT);
    expect(ok.blockers).toEqual([]);
    // the fields only matter on SLURM hosts
    expect(checkDraft({ ...OK, partition: "gpu a100" }, G1, PROJECT).blockers).toEqual([]);
  });

  test("queue off: seeds that cannot start block Launch", () => {
    expect(checkDraft({ ...OK, queue: false }, G1, PROJECT).blockers).toEqual([
      "2 won't start: 1 GPU free; turn on Queue",
    ]);
  });

  test("the hub never queues: seeds beyond its free GPUs block Launch", () => {
    const hub = launchHost({ name: "local", kind: "hub", projects: null, gpus: [gpu(0), gpu(1)] });
    expect(checkDraft({ ...OK, host: "local" }, hub, PROJECT).blockers).toEqual([
      "1 won't start: 2 GPU free on local",
    ]);
  });

  test("after a partial launch, only the seeds not started need free GPUs", () => {
    // seed 4 started on the hub and now holds GPU 0; seed 5 was refused and is sent again
    const hub = launchHost({ name: "local", kind: "hub", projects: null, gpus: [gpu(0, { run_id: "r-s4" }), gpu(1)] });
    const draft = { ...OK, host: "local", seeds: "4, 5" };
    expect(checkDraft(draft, hub, PROJECT).blockers).toEqual(["1 won't start: 1 GPU free on local"]);
    const retry = checkDraft(draft, hub, PROJECT, Date.now(), [4]);
    expect(retry.blockers).toEqual([]);
    expect([retry.seeds, retry.pending]).toEqual([[4, 5], [5]]);
    expect(retry.plan).toEqual({ now: 1, queued: 0, blocked: 0, cvd: [1], firstPos: null });
  });

  test("{config} without a config var blocks: hx --config files are not sent with a launch", () => {
    const cmd = "python train.py --config {config} --seed {seed}";
    const c = checkDraft({ ...OK, command: cmd }, G1, PROJECT);
    expect(c.commandError).toBe(CONFIG_ERROR);
    expect(c.blockers).toEqual([`command: ${CONFIG_ERROR}`]);
    // a template run that set the config as a var carries it: the slot fills
    const carried = checkDraft({ ...OK, command: cmd }, G1, PROJECT, Date.now(), [], { config: "configs/aug.yaml" });
    expect(carried.blockers).toEqual([]);
  });

  test("warnings: no {seed} with several seeds, and shell operators", () => {
    expect(checkDraft({ ...OK, command: "python train.py" }, G1, PROJECT).warnings).toEqual([NO_SEED_WARNING]);
    expect(checkDraft({ ...OK, seeds: "4", command: "python train.py" }, G1, PROJECT).warnings).toEqual([]);
    expect(
      checkDraft({ ...OK, command: "python a.py --seed {seed} && echo done" }, G1, PROJECT).warnings,
    ).toEqual(["&& is passed to the program as text; use sh -c '…' for shell syntax"]);
  });
});

test("Queue cannot make a request larger than the host's total GPU capacity runnable", () => {
  const host = launchHost({ gpus: [gpu(0), gpu(1)] });
  expect(checkDraft({ ...OK, gpus: 4, queue: true }, host, PROJECT).blockers).toContain("4 GPUs requested; gpu1 has 2");
  expect(checkDraft({ ...OK, gpus: 2, queue: true }, host, PROJECT).blockers).toEqual([]);
  expect(checkDraft({ ...OK, gpus: 0 }, host, PROJECT).blockers).toEqual([]);
  expect(checkDraft({ ...OK, gpus: 4 }, { ...host, kind: "slurm" }, PROJECT).blockers).toEqual([]);
  expect(checkDraft({ ...OK, gpus: 4 }, { ...host, state: "disabled", gpus: [] }, PROJECT).blockers.some((message) => message.includes("has 0"))).toBe(false);
});
