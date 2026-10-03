import { describe, expect, test } from "bun:test";

import {
  SEED_HINT,
  fillSeed,
  hasSeedSlot,
  splitCommand,
  templateSegments,
} from "../../src/launch/command";
import { shellJoin } from "../../src/pages/components/format";

describe("splitCommand", () => {
  test("splits on whitespace", () => {
    expect(splitCommand("python train.py  --lr 3e-4\t--seed {seed}")).toEqual({
      argv: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
      error: null,
      operators: [],
    });
  });

  test("honours single quotes, double quotes and backslashes like sh", () => {
    expect(splitCommand(`python -c 'print("a b")' --name "x y" a\\ b`).argv).toEqual([
      "python",
      "-c",
      'print("a b")',
      "--name",
      "x y",
      "a b",
    ]);
    expect(splitCommand(`echo "say \\"hi\\" \\$HOME \\n"`).argv).toEqual(["echo", 'say "hi" $HOME \\n']);
    expect(splitCommand("echo '' x").argv).toEqual(["echo", "", "x"]);
    expect(splitCommand("python a.py \\\n  --x 1").argv).toEqual(["python", "a.py", "--x", "1"]);
  });

  test("reports unclosed quotes and a trailing backslash", () => {
    expect(splitCommand("python 'oops")).toEqual({ argv: [], error: "unclosed ' quote", operators: [] });
    expect(splitCommand('python "oops')).toEqual({ argv: [], error: 'unclosed " quote', operators: [] });
    expect(splitCommand("python oops\\")).toEqual({ argv: [], error: "trailing \\", operators: [] });
  });

  test("keeps an empty text empty", () => {
    expect(splitCommand("  \n ")).toEqual({ argv: [], error: null, operators: [] });
  });

  test("flags unquoted shell operators, not quoted ones", () => {
    expect(splitCommand("python a.py && python b.py").operators).toEqual(["&&"]);
    expect(splitCommand("python a.py '&&' x > out.txt").operators).toEqual([">"]);
  });

  test("round-trips shellJoin", () => {
    const argv = ["python", "it's", "", "a b", "--seed={seed}", 'say "x"'];
    expect(splitCommand(shellJoin(argv)).argv).toEqual(argv);
  });
});

test("templateSegments marks every {seed}", () => {
  expect(templateSegments("python t.py --seed {seed} --out r{seed}")).toEqual([
    { text: "python t.py --seed ", seed: false },
    { text: "{seed}", seed: true },
    { text: " --out r", seed: false },
    { text: "{seed}", seed: true },
  ]);
  expect(templateSegments("")).toEqual([]);
  expect(templateSegments("no slot")).toEqual([{ text: "no slot", seed: false }]);
});

test("fillSeed and hasSeedSlot", () => {
  expect(fillSeed(["python", "--seed={seed}", "{seed}{seed}"], 7)).toEqual(["python", "--seed=7", "77"]);
  expect(hasSeedSlot(["python", "--seed={seed}"])).toBe(true);
  expect(hasSeedSlot(["python", "--seed", "3"])).toBe(false);
});

test("the hint tells the user to quote {seed} in a shell", () => {
  expect(SEED_HINT).toBe("{seed} is filled with each seed. In a shell, quote it: '{seed}'");
});
