/**
 * The processes one demo invocation owns, and how to kill them all.
 *
 * `hx serve` starts its fake hosts, and each host its run supervisors, in their own
 * sessions (`start_new_session`), so they are not in the hub's process group and outlive a
 * hub that crashes or is killed. They are found instead by the invocation's own directory
 * (`RUN_DIR` in `paths.ts`): every one of them has a `--home` under it on its command line.
 * A run's command names no home, so the descendants of every owned process are owned too.
 * Another suite's directory is a different one, so its processes are never matched.
 */
import { spawnSync } from "node:child_process";

export interface Proc {
  pid: number;
  ppid: number;
  pgid: number;
  command: string;
}

const PS_ROW = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/;

/** Rows of `ps -axo pid=,ppid=,pgid=,command=` (full command lines on macOS and Linux). */
export function parsePs(out: string): Proc[] {
  const procs: Proc[] = [];
  for (const line of out.split("\n")) {
    const m = PS_ROW.exec(line);
    if (!m) continue;
    procs.push({ pid: Number(m[1]), ppid: Number(m[2]), pgid: Number(m[3]), command: m[4] ?? "" });
  }
  return procs;
}

/** Every process on this machine, now. */
export function listProcs(): Proc[] {
  const out = spawnSync("ps", ["-axo", "pid=,ppid=,pgid=,command="], { encoding: "utf8" });
  return parsePs(out.stdout ?? "");
}

export interface Owner {
  /** A directory only this invocation uses; a process whose command line names it is owned. */
  marker: string;
  /** Processes owned outright (the hub). */
  roots: number[];
  /** Process groups owned outright (the hub's: its children stay in it after it dies). */
  groups: number[];
  /** Never owned (the caller itself). */
  exclude: number[];
}

/** The processes of `procs` that `owner` owns, with every descendant of each. */
export function ownedBy(procs: Proc[], owner: Owner): Proc[] {
  const excluded = new Set(owner.exclude);
  const owned = new Set<number>();
  for (const p of procs) {
    if (excluded.has(p.pid)) continue;
    const named = owner.marker !== "" && p.command.includes(owner.marker);
    if (named || owner.roots.includes(p.pid) || owner.groups.includes(p.pgid)) owned.add(p.pid);
  }
  let grew = true;
  while (grew) {
    grew = false;
    for (const p of procs) {
      if (!owned.has(p.pid) && !excluded.has(p.pid) && owned.has(p.ppid)) {
        owned.add(p.pid);
        grew = true;
      }
    }
  }
  return procs.filter((p) => owned.has(p.pid));
}

/**
 * Process groups that are safe to kill whole: every live member is owned and none is one
 * of `keep` (the caller's own group).
 */
export function killableGroups(procs: Proc[], owned: Proc[], keep: number[]): number[] {
  const mine = new Set(owned.map((p) => p.pid));
  const groups = new Set(owned.map((p) => p.pgid));
  for (const p of procs) if (!mine.has(p.pid)) groups.delete(p.pgid);
  for (const g of keep) groups.delete(g);
  return [...groups];
}

function signal(target: number): void {
  try {
    process.kill(target, "SIGKILL");
  } catch {
    // already gone
  }
}

/**
 * SIGKILL every process `owner` owns, whole groups where that is safe, and look again
 * until none is left (a dying supervisor may still start one) or `rounds` run out.
 * Returns what was still there on the last look.
 */
export async function killOwned(owner: Owner, keepGroups: number[], rounds = 10): Promise<Proc[]> {
  let left: Proc[] = [];
  for (let i = 0; i < rounds; i++) {
    const procs = listProcs();
    left = ownedBy(procs, owner);
    if (left.length === 0) return [];
    for (const g of killableGroups(procs, left, keepGroups)) signal(-g);
    for (const p of left) signal(p.pid);
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return ownedBy(listProcs(), owner);
}
