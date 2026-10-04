import { describe, expect, test } from "bun:test";
import { killableGroups, ownedBy, parsePs, type Proc } from "../../e2e/procs";

const RUN = "/repo/ui/e2e/.runs/run-AbC123";

/** pid ppid pgid command */
const TABLE: Proc[] = [
  { pid: 1, ppid: 0, pgid: 1, command: "/sbin/launchd" },
  { pid: 50, ppid: 1, pgid: 50, command: "bun e2e/serve-demo.ts --with-hosts" },
  // the hub, in its own group, and a child of it in that group
  { pid: 60, ppid: 50, pgid: 60, command: `/venv/bin/hx --home ${RUN}/home-hosts serve --port 4100` },
  { pid: 61, ppid: 60, pgid: 60, command: "/venv/bin/python -c helper" },
  // a fake host the hub started in its own session, and a supervisor that host started
  { pid: 70, ppid: 60, pgid: 70, command: `python -m hypothex.cli.main --home ${RUN}/home-hosts/demo-hosts/gpu1 serve` },
  { pid: 80, ppid: 70, pgid: 80, command: `python -m hypothex.core.supervisor r1 --home ${RUN}/home-hosts/demo-hosts/gpu1` },
  // the run's command, in its own session, whose command line names no home
  { pid: 81, ppid: 80, pgid: 81, command: "python train.py --seed 1" },
  // an orphaned fake host of a hub that died: reparented to launchd, found by its home
  { pid: 90, ppid: 1, pgid: 90, command: `python -m hypothex.cli.main --home ${RUN}/home-hosts/demo-hosts/cluster serve` },
  // an orphaned hub child: no marker, but still in the hub's group
  { pid: 62, ppid: 1, pgid: 60, command: "/venv/bin/python -c orphan" },
  // another suite's demo, and an unrelated process
  { pid: 200, ppid: 1, pgid: 200, command: "python -m hypothex.cli.main --home /repo/ui/e2e/.runs/run-Other9/home serve" },
  { pid: 300, ppid: 1, pgid: 300, command: "vim notes.txt" },
  // shares a group with an unrelated leader: never killed as a group
  { pid: 301, ppid: 300, pgid: 300, command: `tail -f ${RUN}/home/serve/log` },
];

describe("parsePs", () => {
  test("reads pid, ppid, pgid and the full command line", () => {
    const out = "    1     0     1 /sbin/launchd\n  60    50    60 /venv/bin/hx --home /a b/c serve\n\n";
    expect(parsePs(out)).toEqual([
      { pid: 1, ppid: 0, pgid: 1, command: "/sbin/launchd" },
      { pid: 60, ppid: 50, pgid: 60, command: "/venv/bin/hx --home /a b/c serve" },
    ]);
  });

  test("skips lines that are not a process row", () => {
    expect(parsePs("garbage\n  12 x 3 cmd\n")).toEqual([]);
  });
});

describe("ownedBy", () => {
  const pids = (procs: Proc[]) => procs.map((p) => p.pid).sort((a, b) => a - b);

  test("roots, processes naming the run directory, the given groups, and every descendant", () => {
    const owned = ownedBy(TABLE, { marker: RUN, roots: [60], groups: [60], exclude: [50] });
    expect(pids(owned)).toEqual([60, 61, 62, 70, 80, 81, 90, 301]);
  });

  test("never another run's processes, unrelated ones, or excluded ones", () => {
    const owned = pids(ownedBy(TABLE, { marker: RUN, roots: [50], groups: [], exclude: [50] }));
    expect(owned).not.toContain(50);
    expect(owned).not.toContain(200);
    expect(owned).not.toContain(300);
  });

  test("an empty marker matches nothing by command line", () => {
    expect(ownedBy(TABLE, { marker: "", roots: [], groups: [], exclude: [] })).toEqual([]);
  });
});

describe("killableGroups", () => {
  test("only groups whose every live member is owned, never the caller's own group", () => {
    const owned = ownedBy(TABLE, { marker: RUN, roots: [60], groups: [60], exclude: [50] });
    expect(killableGroups(TABLE, owned, [50]).sort((a, b) => a - b)).toEqual([60, 70, 80, 81, 90]);
  });
});
