import { expect, test } from "bun:test";

import { cliQuote, launchCli, launchCliLine, sbatchLine } from "../../src/launch/cli";
import { slurmBody } from "../../src/launch/plan";
import type { LaunchSpec } from "../../src/launch/plan";
import { launchHost } from "./fixtures";

const SPEC: LaunchSpec = {
  host: launchHost({ name: "gpu1", kind: "ssh" }),
  project: "rxn-forward",
  repo: "/Users/sv/code/rxn-forward",
  commit: null,
  task: "uspto-forward-top1",
  argv: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
  hypothesis: "beam 10 at lr 3e-4 holds",
  gpus: 1,
  queue: true,
  slurm: null,
  params: {},
  vars: {},
};
const TAIL = "-H 'beam 10 at lr 3e-4 holds' -- python train.py --lr 3e-4 --seed '{seed}'";

test("quotes leading equals so zsh cannot expand the copied argument", () => {
  expect(cliQuote("=ls")).toBe("'=ls'");
  expect(cliQuote("=unknown-command")).toBe("'=unknown-command'");
  expect(cliQuote("--name=x")).toBe("--name=x");
  expect(launchCliLine({ ...SPEC, argv: ["python", "=ls"] }, 4)).toEndWith("-- python '=ls'");
});

test("cliQuote leaves plain words alone and quotes braces, spaces, quotes and $", () => {
  expect(cliQuote("train.py")).toBe("train.py");
  expect(cliQuote("3e-4")).toBe("3e-4");
  expect(cliQuote("{seed}")).toBe("'{seed}'");
  expect(cliQuote("--seed={seed}")).toBe("'--seed={seed}'");
  expect(cliQuote("a b")).toBe("'a b'");
  expect(cliQuote("it's")).toBe(`'it'"'"'s'`);
  expect(cliQuote("")).toBe("''");
  expect(cliQuote("$HOME")).toBe("'$HOME'");
});

test("one hx launch line per seed on an ssh host, with --queue", () => {
  expect(launchCli(SPEC, [4, 5])).toBe(
    [
      `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --queue --seed 4 ${TAIL}`,
      `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --queue --seed 5 ${TAIL}`,
    ].join("\n"),
  );
  expect(launchCliLine({ ...SPEC, queue: false }, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --seed 4 ${TAIL}`,
  );
});

test("a SLURM host gets --partition, --time and --account only when filled in, never --queue", () => {
  const spec: LaunchSpec = {
    ...SPEC,
    host: launchHost({ name: "mccleary", kind: "slurm" }),
    gpus: 2,
    slurm: { partition: "gpu", account: "", time: "08:00:00" },
  };
  expect(launchCliLine(spec, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host mccleary --gpus 2 --partition gpu --time 08:00:00 --seed 4 ${TAIL}`,
  );
  const account: LaunchSpec = { ...spec, slurm: { partition: "", account: "lab one", time: "1-00:00:00" } };
  expect(launchCliLine(account, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host mccleary --gpus 2 --time 1-00:00:00 --account 'lab one' --seed 4 ${TAIL}`,
  );
  // all blank: the host's partition, account and time apply, so no flag is sent
  const blank: LaunchSpec = { ...spec, slurm: { partition: "", account: "", time: " " } };
  expect(launchCliLine(blank, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host mccleary --gpus 2 --seed 4 ${TAIL}`,
  );
});

test("a SLURM job with 0 GPUs says --gpus 0: an omitted --gpus keeps the host's default", () => {
  const spec: LaunchSpec = {
    ...SPEC,
    host: launchHost({ name: "mccleary", kind: "slurm" }),
    gpus: 0,
    slurm: { partition: "", account: "", time: "" },
  };
  // the dialog sends slurm.gpus = 0; the pasted line must ask for the same allocation
  expect(slurmBody(spec.slurm ?? { partition: "", account: "", time: "" }, spec.gpus).gpus).toBe(0);
  expect(launchCliLine(spec, 4)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host mccleary --gpus 0 --seed 4 ${TAIL}`,
  );
  // off SLURM, 0 GPUs is the CLI's own default: no flag
  expect(launchCliLine({ ...SPEC, gpus: 0 }, 4)).not.toContain("--gpus");
});

test("the hub has no --host; params and vars carry over; quotes in the hypothesis survive", () => {
  const spec: LaunchSpec = {
    ...SPEC,
    host: launchHost({ name: "local", kind: "hub", projects: null }),
    task: null,
    gpus: 0,
    hypothesis: `it's "fast" `,
    params: { lr: "3e-4" },
    vars: { config: "configs/aug.yaml" },
  };
  expect(launchCliLine(spec, 7)).toBe(
    `hx launch --repo /Users/sv/code/rxn-forward --seed 7 --param lr=3e-4 --var config=configs/aug.yaml -H 'it'"'"'s "fast"' -- python train.py --lr 3e-4 --seed '{seed}'`,
  );
});

test("a pinned commit is named in a comment line: hx launch has no commit flag", () => {
  const sha = "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37";
  expect(launchCli({ ...SPEC, commit: sha }, [4]).split("\n")).toEqual([
    `# code: commit ${sha}; hx launch runs the checkout as it is`,
    `hx launch --repo /Users/sv/code/rxn-forward -t uspto-forward-top1 --host gpu1 --gpus 1 --queue --seed 4 ${TAIL}`,
  ]);
  expect(launchCli(SPEC, [4]).startsWith("hx launch ")).toBe(true);
});

test("sbatchLine shows the flags hx passes to sbatch", () => {
  expect(sbatchLine({ partition: "gpu", account: "", time: "08:00:00" }, 2)).toBe(
    "sbatch --partition gpu --time 08:00:00 --gpus 2",
  );
  expect(sbatchLine({ partition: "", account: "lab", time: " 30 " }, 0)).toBe("sbatch --time 30 --account lab");
  expect(sbatchLine({ partition: "", account: "", time: "" }, 2)).toBe("sbatch --gpus 2");
});

test("sbatchLine and the CLI line set exactly the SLURM fields slurmBody sends", () => {
  const cases = [
    { partition: " gpu ", account: "", time: "08:00:00" },
    { partition: "", account: " lab ", time: " " },
    { partition: "\t", account: "", time: " 2-0 " },
  ];
  for (const fields of cases) {
    const sent = Object.entries(slurmBody(fields, 2)).filter(([key]) => key !== "gpus");
    const flags = sent.map(([key, value]) => `--${key} ${value}`);
    const host = launchHost({ name: "mccleary", kind: "slurm" });
    const cli = launchCliLine({ ...SPEC, host, gpus: 2, slurm: fields }, 4);
    for (const line of [sbatchLine(fields, 2), cli]) {
      for (const flag of flags) expect(line).toContain(flag);
      expect(line.match(/--(partition|time|account) /g) ?? []).toHaveLength(flags.length);
    }
  }
});
