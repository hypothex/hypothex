/**
 * Regression check for the shutdown order of `serve-demo.ts --with-hosts`. Run it alone,
 * never next to Playwright: `bun e2e/shutdown-check.ts` (from ui/, after `bun run build`).
 *
 * It starts the hosts demo on a port the OS reports free (never a fixed one) and its own
 * home (`e2e/.home-shutdown`, wiped first). Before it reads any host or run route it waits
 * until the hub on that port answers with the identity `serve-demo.ts` wrote into that home,
 * so it can never query another `hx serve` (one on the real `~/.hypothex` would list the
 * user's real hosts). If `serve-demo.ts` cannot start or exits while it waits, it fails at
 * once. Then it waits until the fake hosts are connected and a demo run runs on one, and
 * sends SIGTERM to the web server's process group, as Playwright's `gracefulShutdown` does.
 * `serve-demo.ts` forwards it to the hub alone; the hub's ASGI lifespan shutdown stops the
 * demo runs, then the fake hosts. The check fails if any process of that home is left
 * afterwards: the hub, a fake host's `hx serve`, or a demo run's supervisor (its `--home`
 * lies under the demo home). Killing the fake hosts before the hub's cleanup leaves exactly
 * those supervisors behind.
 */
import { spawn, spawnSync } from "node:child_process";
import { rmSync } from "node:fs";
import { join } from "node:path";
import { answersAs, E2E_DIR, freePort, HOSTS_DEMO_LABEL, type Identity, readIdentity, SHUTDOWN_WAIT_MS } from "./paths";

const PORT = freePort();
const HOME = join(E2E_DIR, ".home-shutdown");
const BASE = `http://127.0.0.1:${PORT}`;

interface HostLite {
  name: string;
  state: { state: string; environment_id: string | null };
}

// a stale identity file of an earlier check must never vouch for another server
rmSync(HOME, { recursive: true, force: true });

const child = spawn("bun", ["e2e/serve-demo.ts", "--with-hosts"], {
  env: { ...process.env, HX_E2E_HOSTS_PORT: String(PORT), HX_E2E_HOSTS_HOME: HOME },
  stdio: "inherit",
  detached: true,
});
let startError: Error | null = null;
child.on("error", (err) => {
  startError = err;
});
const ended = (): boolean => startError !== null || child.exitCode !== null || child.signalCode !== null;

/** Throw at once when `serve-demo.ts` failed to start or has exited: nothing will answer. */
function stillUp(what: string): void {
  if (startError !== null) throw new Error(`serve-demo.ts did not start (${startError.message}); was waiting for ${what}`);
  if (ended()) {
    throw new Error(`serve-demo.ts exited (code ${child.exitCode}, signal ${child.signalCode}); was waiting for ${what}`);
  }
}

/** Poll `ok` every 500 ms until it holds, or throw after `ms`; `live` also requires the demo to run. */
async function waitUntil(what: string, ok: () => Promise<boolean> | boolean, ms: number, live = true): Promise<void> {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (live) stillUp(what);
    if (await ok()) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`timed out after ${ms} ms waiting for ${what}`);
}

/** Set once the hub on `PORT` proved it serves `HOME`; no other route is read before. */
let verified: Identity | null = null;

async function getJson<T>(path: string): Promise<T | null> {
  if (verified === null) throw new Error(`refusing GET ${path}: the hub on ${PORT} is not verified yet`);
  try {
    const response = await fetch(`${BASE}${path}`);
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}

/**
 * `pid command` of every process whose command line names the check's home (`ps` gives
 * full command lines on macOS and Linux alike; this script's own command line does not
 * name the home).
 */
function leftovers(): string[] {
  const out = spawnSync("ps", ["-axo", "pid=,command="], { encoding: "utf8" });
  return out.stdout.split("\n").filter((line) => line.includes(HOME));
}

let failure: string | null = null;
try {
  await waitUntil(
    `the hub on ${PORT} to answer with the identity of ${HOME}`,
    async () => {
      const want = readIdentity(HOME);
      if (want === null || want.label !== HOSTS_DEMO_LABEL || !(await answersAs(BASE, want))) return false;
      verified = want;
      return true;
    },
    180_000,
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
  );
  const envs = new Set(remote.map((h) => h.state.environment_id));
  await waitUntil(
    "a demo run running on a fake host",
    async () => {
      const runs = (await getJson<{ environment_id: string }[]>("/api/v1/runs?status=running&limit=50")) ?? [];
      return runs.some((r) => envs.has(r.environment_id));
    },
    60_000,
  );
  const before = leftovers();
  if (!before.some((line) => line.includes("hypothex.core.supervisor"))) {
    throw new Error(`no demo supervisor runs before the stop, so the check would prove nothing:\n${before.join("\n")}`);
  }
  // what Playwright's gracefulShutdown does: SIGTERM to the web server's process group
  process.kill(-(child.pid as number), "SIGTERM");
  await waitUntil("serve-demo.ts to exit", ended, SHUTDOWN_WAIT_MS + 30_000, false);
  // a stopped supervisor writes its record and exits; give it a moment
  await new Promise((resolve) => setTimeout(resolve, 3_000));
  const left = leftovers();
  if (left.length > 0) failure = `left running after the stop:\n${left.join("\n")}`;
} catch (err) {
  failure = err instanceof Error ? err.message : String(err);
} finally {
  if (!ended() && child.pid !== undefined) {
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch {
      // already gone
    }
  }
  spawnSync("pkill", ["-9", "-f", HOME]);
  rmSync(HOME, { recursive: true, force: true });
}
if (failure !== null) {
  console.error(`shutdown-check FAILED: ${failure}`);
  process.exit(1);
}
console.log("shutdown-check ok: the hub stopped its demo runs and fake hosts; nothing of the demo home is left");
