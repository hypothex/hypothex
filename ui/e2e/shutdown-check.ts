/**
 * Regression check for how `serve-demo.ts --with-hosts` ends: `bun e2e/shutdown-check.ts`
 * (from ui/, after `bun run build`). CI runs it after the Playwright suite.
 *
 * It uses its own run directory (`RUN_DIR` from `paths.ts`, new for each check) and a port
 * the OS reports free, so it can run next to a Playwright suite. Each case starts the hosts
 * demo there, waits until the hub on that port answers with the identity `serve-demo.ts`
 * wrote into its home (so it never reads another `hx serve`, e.g. one on the real
 * `~/.hypothex`), then until the fake hosts are connected and a demo run runs on one. Then
 * it ends the demo in one of three ways:
 *
 * - `sigterm`: SIGTERM to the web server's process group, as Playwright's
 *   `gracefulShutdown` does. `serve-demo.ts` forwards it to the hub alone; the hub's ASGI
 *   lifespan shutdown stops the demo runs, then the fake hosts.
 * - `hub-killed`: SIGKILL to the hub, as a crash. Its fake hosts and supervisors run in
 *   their own sessions, so they outlive it; `serve-demo.ts` must kill them.
 * - `hub-stuck`: SIGSTOP to the hub, then the SIGTERM above, with a short shutdown wait. The
 *   hub never exits, so `serve-demo.ts` must kill it and everything else when the wait ends.
 *
 * Each case fails if any process of the demo is left afterwards: one that names the run
 * directory on its command line (the hub, a fake host, a supervisor), or one that was a
 * descendant of the demo before the stop (a run's own command names no home).
 */
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import {
  answersAs,
  localToken,
  freePort,
  HOSTS_DEMO_LABEL,
  HOSTS_HOME_DIR,
  type Identity,
  readIdentity,
  RUN_DIR,
} from "./paths";
import { listProcs, ownedBy, type Proc } from "./procs";

const HOME = HOSTS_HOME_DIR;
/** The shutdown wait `serve-demo.ts` gets in the `hub-stuck` case. */
const SHORT_WAIT_MS = 5_000;

interface HostLite {
  name: string;
  state: { state: string; environment_id: string | null };
}

type Case = "sigterm" | "hub-killed" | "hub-stuck";

/** Poll `ok` every 500 ms until it holds, or throw after `ms`. */
async function waitUntil(what: string, ok: () => Promise<boolean> | boolean, ms: number, alive?: () => void): Promise<void> {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    alive?.();
    if (await ok()) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`timed out after ${ms} ms waiting for ${what}`);
}

/** Every process of the demo now: it names the run directory, or descends from `serve-demo.ts`. */
function demoProcs(root: number): Proc[] {
  return ownedBy(listProcs(), { marker: `${RUN_DIR}/`, roots: [root], groups: [], exclude: [process.pid] });
}

/** The hub's pid from `serve/server.json` in its home. */
function hubPid(): number {
  const info = JSON.parse(readFileSync(join(HOME, "serve", "server.json"), "utf8")) as { pid: number };
  return info.pid;
}

async function runCase(which: Case): Promise<string | null> {
  const port = freePort();
  const base = `http://127.0.0.1:${port}`;
  // a stale identity file of an earlier case must never vouch for another server
  rmSync(HOME, { recursive: true, force: true });
  const env: Record<string, string | undefined> = { ...process.env, HX_E2E_HOSTS_PORT: String(port) };
  if (which === "hub-stuck") env.HX_E2E_SHUTDOWN_WAIT_MS = String(SHORT_WAIT_MS);
  const child = spawn("bun", ["e2e/serve-demo.ts", "--with-hosts"], { env, stdio: "inherit", detached: true });
  let startError: Error | null = null;
  child.on("error", (err) => {
    startError = err;
  });
  const ended = (): boolean => startError !== null || child.exitCode !== null || child.signalCode !== null;
  const stillUp = (): void => {
    if (startError !== null) throw new Error(`serve-demo.ts did not start (${(startError as Error).message})`);
    if (ended()) throw new Error(`serve-demo.ts exited early (code ${child.exitCode}, signal ${child.signalCode})`);
  };

  let verified: Identity | null = null;
  const getJson = async <T>(path: string): Promise<T | null> => {
    if (verified === null) throw new Error(`refusing GET ${path}: the hub on ${port} is not verified yet`);
    try {
      const response = await fetch(`${base}${path}`, { headers: { Authorization: `Bearer ${localToken(HOME)}` } });
      return response.ok ? ((await response.json()) as T) : null;
    } catch {
      return null;
    }
  };

  let before: Proc[] = [];
  try {
    await waitUntil(
      `the hub on ${port} to answer with the identity of ${HOME}`,
      async () => {
        const want = readIdentity(HOME);
        if (want === null || want.label !== HOSTS_DEMO_LABEL || !(await answersAs(base, want))) return false;
        verified = want;
        return true;
      },
      180_000,
      stillUp,
    );
    let remote: HostLite[] = [];
    await waitUntil(
      "the fake hosts to connect",
      async () => {
        const hosts = (await getJson<HostLite[]>("/api/v1/hosts")) ?? [];
        remote = hosts.filter((h) => h.name !== "local");
        return remote.length > 0 && hosts.every((h) => h.state.state === "connected");
      },
      180_000,
      stillUp,
    );
    const envs = new Set(remote.map((h) => h.state.environment_id));
    await waitUntil(
      "a demo run running on a fake host",
      async () => {
        const runs = (await getJson<{ environment_id: string }[]>("/api/v1/runs?status=running&limit=50")) ?? [];
        return runs.some((r) => envs.has(r.environment_id));
      },
      60_000,
      stillUp,
    );
    before = demoProcs(child.pid as number);
    if (!before.some((p) => p.command.includes("hypothex.core.supervisor"))) {
      throw new Error(`no demo supervisor runs before the stop, so the check would prove nothing:\n${show(before)}`);
    }
    const hub = hubPid();
    if (which === "hub-killed") {
      process.kill(hub, "SIGKILL");
    } else {
      if (which === "hub-stuck") process.kill(hub, "SIGSTOP");
      // what Playwright's gracefulShutdown does: SIGTERM to the web server's process group
      process.kill(-(child.pid as number), "SIGTERM");
    }
    await waitUntil("serve-demo.ts to exit", ended, 90_000);
    // a stopped supervisor writes its record and exits; give it a moment
    await new Promise((resolve) => setTimeout(resolve, 3_000));
    const gone = new Set(before.map((p) => `${p.pid} ${p.command}`));
    const left = listProcs().filter(
      (p) => p.pid !== process.pid && (p.command.includes(`${RUN_DIR}/`) || gone.has(`${p.pid} ${p.command}`)),
    );
    return left.length > 0 ? `left running after the stop:\n${show(left)}` : null;
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  } finally {
    // never leave anything behind, whatever the outcome
    for (const p of [...before, ...demoProcs(child.pid ?? -1)]) {
      try {
        process.kill(p.pid, "SIGKILL");
      } catch {
        // already gone
      }
    }
    spawnSync("pkill", ["-9", "-f", RUN_DIR]);
  }
}

function show(procs: Proc[]): string {
  return procs.map((p) => `${p.pid} ${p.command}`).join("\n");
}

const only = process.argv.slice(2) as Case[];
const cases: Case[] = only.length > 0 ? only : ["sigterm", "hub-killed", "hub-stuck"];
const failures: string[] = [];
for (const which of cases) {
  console.log(`shutdown-check: ${which}`);
  const failure = await runCase(which);
  if (failure !== null) failures.push(`${which}: ${failure}`);
  else console.log(`shutdown-check: ${which} ok`);
}
rmSync(RUN_DIR, { recursive: true, force: true });
if (failures.length > 0) {
  console.error(`shutdown-check FAILED\n${failures.join("\n\n")}`);
  process.exit(1);
}
console.log(`shutdown-check ok (${cases.join(", ")}): nothing of the demo is left`);
