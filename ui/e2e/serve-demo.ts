/**
 * Playwright `webServer` command: seed a fresh demo home, then serve it.
 *
 * Without arguments: wipes `e2e/.home`, writes its identity (`environment.json`: a new
 * `environment_id` and the label `DEMO_LABEL`), runs `hx demo --json` into it, writes the
 * kind → "project/task" map to `e2e/.demo.json`, then runs `hx serve` on `PORT`.
 *
 * With `--with-hosts`: the same with `hx demo --with-hosts --json` into `HOSTS_HOME_DIR`,
 * label `HOSTS_DEMO_LABEL`, output in `e2e/.demo-hosts.json`, served on `HOSTS_PORT`. Its
 * hosts are fake (env servers on this machine reached by `route: url`). `HYPOTHEX_SSH` and
 * `HYPOTHEX_SCP` are `false` for both servers, so nothing started here can open a real SSH
 * connection. `PORT` and `HOSTS_PORT` are the run's random ports (`e2e/paths.ts`).
 *
 * A child that cannot start (no `uv`, no venv `hx`, `hx demo` failing, `hx serve` not
 * spawning or exiting, e.g. on a taken port) ends this script at once with exit code 1 or
 * the child's code, so Playwright and `shutdown-check.ts` stop waiting immediately.
 *
 * Shutdown order: Playwright sends SIGTERM to this script's process group
 * (`gracefulShutdown`). `hx serve` runs in its own group (`detached`), so it does not get
 * that signal; this script forwards SIGTERM to the hub process alone and waits for it to
 * exit. The hub's ASGI lifespan shutdown, which uvicorn runs on that SIGTERM before it
 * exits (the backend plan, ruling S9), stops the demo runs over the fake gpu1 server's
 * HTTP API, then the fake hosts. Only then (or after `SHUTDOWN_WAIT_MS`) is the rest of the
 * group SIGKILLed. Killing the group first would take the fake hosts down before that
 * cleanup and orphan the demo runs' supervisors.
 */
import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  DEMO_FILE,
  DEMO_LABEL,
  HOME_DIR,
  HOSTS_DEMO_FILE,
  HOSTS_DEMO_LABEL,
  HOSTS_HOME_DIR,
  HOSTS_PORT,
  IDENTITY_FILE,
  PORT,
  REPO_ROOT,
  SHUTDOWN_WAIT_MS,
  UI_DIST_INDEX,
} from "./paths";

const withHosts = process.argv.includes("--with-hosts");
const home = withHosts ? HOSTS_HOME_DIR : HOME_DIR;
const demoFile = withHosts ? HOSTS_DEMO_FILE : DEMO_FILE;
const port = withHosts ? HOSTS_PORT : PORT;
const label = withHosts ? HOSTS_DEMO_LABEL : DEMO_LABEL;
const env = { ...process.env, HYPOTHEX_SSH: "false", HYPOTHEX_SCP: "false" };

if (!existsSync(UI_DIST_INDEX)) {
  console.error(`missing ${UI_DIST_INDEX}: run "bun run build" in ui/ first`);
  process.exit(1);
}

/** The project venv's `hx`, so signals reach `hx serve` itself and not a `uv run` wrapper. */
function venvHx(): string {
  const found = spawnSync(
    "uv",
    ["run", "--project", REPO_ROOT, "python", "-c", "import os, sys; print(os.path.join(os.path.dirname(sys.executable), 'hx'))"],
    { cwd: REPO_ROOT, encoding: "utf8", env, stdio: ["ignore", "pipe", "inherit"] },
  );
  const path = (found.stdout ?? "").trim();
  if (found.status !== 0 || !existsSync(path)) {
    console.error(`cannot find the venv's hx (uv run exited ${found.status}, got "${path}")`);
    process.exit(1);
  }
  return path;
}

rmSync(home, { recursive: true, force: true });
mkdirSync(home, { recursive: true });
// the same two keys `load_descriptor` writes; the specs compare the hub's answer with them
writeFileSync(
  join(home, IDENTITY_FILE),
  JSON.stringify({ environment_id: randomUUID().replace(/-/g, ""), label }, null, 2),
);

const hx = venvHx();
const demoArgs = withHosts ? ["demo", "--with-hosts", "--json"] : ["demo", "--json"];
const seeded = spawnSync(hx, ["--home", home, ...demoArgs], {
  cwd: REPO_ROOT,
  encoding: "utf8",
  env,
  stdio: ["ignore", "pipe", "inherit"],
});
if (seeded.status !== 0) {
  const why = seeded.error ? seeded.error.message : `exit code ${seeded.status}`;
  console.error(`hx ${demoArgs.join(" ")} failed: ${why}`);
  process.exit(1);
}
writeFileSync(demoFile, seeded.stdout);

const server: ChildProcess = spawn(hx, ["--home", home, "serve", "--port", String(port)], {
  cwd: REPO_ROOT,
  env,
  stdio: "inherit",
  detached: true,
});
// the hub could not be spawned at all: stop now, nothing else will ever answer on the port
server.on("error", (err) => {
  console.error(`hx serve did not start: ${err.message}`);
  process.exit(1);
});
let exited = server.exitCode !== null;
server.on("exit", () => {
  exited = true;
});

/** SIGKILL whatever is left in the hub's process group (fake hosts of a hub that died). */
function killGroup(): void {
  if (server.pid === undefined) return;
  try {
    process.kill(-server.pid, "SIGKILL");
  } catch {
    // the group is already gone
  }
}

let stopping = false;
/** SIGTERM the hub alone, wait for its lifespan cleanup and exit, then clear the group. */
async function stop(): Promise<void> {
  if (stopping) return;
  stopping = true;
  if (server.pid !== undefined && !exited) {
    try {
      process.kill(server.pid, "SIGTERM");
    } catch {
      // already gone
    }
    const deadline = Date.now() + SHUTDOWN_WAIT_MS;
    while (!exited && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 200));
    if (!exited) console.error(`hx serve did not exit within ${SHUTDOWN_WAIT_MS} ms; killing its group`);
  }
  killGroup();
  process.exit(0);
}
process.on("SIGINT", () => void stop());
process.on("SIGTERM", () => void stop());
// the hub ended by itself (failed start, crash or Ctrl-C): clear what it left, keep its exit code
server.on("exit", (code) => {
  if (stopping) return;
  killGroup();
  process.exit(code ?? 1);
});
