/** Paths and constants shared by the Playwright config, the demo server, and the specs. */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_DIR = fileURLToPath(new URL(".", import.meta.url));
export const REPO_ROOT = resolve(E2E_DIR, "..", "..");
export const UI_DIST_INDEX = join(REPO_ROOT, "src", "hypothex", "ui_dist", "index.html");
/** Parent of every run's own directory; nothing outside one run's directory is ever wiped. */
export const RUNS_DIR = join(E2E_DIR, ".runs");

/**
 * This run's own directory, `e2e/.runs/run-XXXXXX`. Like the ports below, the first
 * process that loads this file (the Playwright runner, or `shutdown-check.ts`) creates a
 * fresh one and writes it into `HX_E2E_RUN_DIR`; every child inherits it, so the workers and
 * both `serve-demo.ts` web servers use the same one. Two suites started in the same checkout
 * get two directories, so neither wipes the other's homes or demo files. A given directory
 * must lie inside `RUNS_DIR`, because `serve-demo.ts` wipes the homes in it.
 */
function runDir(): string {
  const given = process.env.HX_E2E_RUN_DIR;
  if (given) {
    const dir = resolve(given);
    const rel = relative(RUNS_DIR, dir);
    if (rel === "" || rel.startsWith("..") || rel.includes("/")) {
      throw new Error(`HX_E2E_RUN_DIR must be a directory directly in ${RUNS_DIR}, got ${given}`);
    }
    mkdirSync(dir, { recursive: true });
    return dir;
  }
  mkdirSync(RUNS_DIR, { recursive: true });
  const dir = mkdtempSync(join(RUNS_DIR, "run-"));
  process.env.HX_E2E_RUN_DIR = dir;
  return dir;
}

export const RUN_DIR = runDir();
/** Hub home of the `hx demo` server, wiped and re-seeded on every server start. */
export const HOME_DIR = join(RUN_DIR, "home");
/** `hx demo --json` output: `{kind: "project/task"}`. */
export const DEMO_FILE = join(RUN_DIR, "demo.json");

/** Run by `node -e` or `bun -e`: bind port 0 on 127.0.0.1, print the port the OS gave, close. */
const FREE_PORT_JS =
  "const s = require('node:net').createServer(); s.listen(0, '127.0.0.1', () => { process.stdout.write(String(s.address().port)); s.close(); });";

/**
 * A TCP port the OS reports free on 127.0.0.1. A child process does the bind, so this
 * stays synchronous (the Playwright config cannot await). Tests can select the Node
 * runtime used by Playwright workers while their own runner remains Bun.
 */
export function freePort(runtime: string = process.execPath): number {
  const out = spawnSync(runtime, ["-e", FREE_PORT_JS], { encoding: "utf8" });
  const port = Number(out.stdout?.trim());
  if (out.status !== 0 || !Number.isInteger(port) || port <= 0) {
    throw new Error(`no free port from the OS: ${out.error?.message ?? out.stderr ?? "no output"}`);
  }
  return port;
}

/**
 * This run's port for `name`. The first process that loads this file (the Playwright
 * runner, or `shutdown-check.ts`) asks the OS for a free port and writes it into its own
 * environment; every child inherits it, so Playwright's workers and both `serve-demo.ts`
 * web servers agree on it. Only this file sets these variables; there is no fixed default.
 */
function runPort(name: string): number {
  const given = Number(process.env[name] ?? "");
  if (Number.isInteger(given) && given > 0) return given;
  const port = freePort();
  process.env[name] = String(port);
  return port;
}

/** Port of the `hx demo` hub (projects light, dark, light-edit, dark-edit). */
export const PORT = runPort("HX_E2E_PORT");
/** Port of the `hx demo --with-hosts` hub (projects hosts-*). */
export const HOSTS_PORT = runPort("HX_E2E_HOSTS_PORT");
/** Vite same-origin proxy used by the authentication acceptance project. */
export const VITE_PORT = runPort("HX_E2E_VITE_PORT");

export const KINDS = [
  "generic",
  "training",
  "agent_eval",
  "agent_iteration",
  "system_bench",
] as const;
export type Kind = (typeof KINDS)[number];

/** Hub home of the `hx demo --with-hosts` server (fake remote hosts), wiped on every start. */
export const HOSTS_HOME_DIR = join(RUN_DIR, "home-hosts");
/** `hx demo --with-hosts --json` output. */
export const HOSTS_DEMO_FILE = join(RUN_DIR, "demo-hosts.json");
/**
 * Labels `serve-demo.ts` writes into each fresh demo home's `environment.json`, with a new
 * `environment_id`; every check compares both with the hub's answer before it uses the hub.
 */
export const DEMO_LABEL = "hx-e2e-demo";
export const HOSTS_DEMO_LABEL = "hx-e2e-hosts";
/** The environment identity file in a Hypothex home (`Layout.environment_json`). */
export const IDENTITY_FILE = "environment.json";
/**
 * How long `serve-demo.ts` waits for `hx serve` to clean up after SIGTERM before it kills
 * every process of the run. `HX_E2E_SHUTDOWN_WAIT_MS` shortens it (the shutdown check).
 */
export const SHUTDOWN_WAIT_MS = Number(process.env.HX_E2E_SHUTDOWN_WAIT_MS ?? "") || 60_000;
/** The route every Hypothex server answers without a token: its environment identity. */
export const IDENTITY_ROUTE = "/.well-known/hypothex/environment";

/** A demo home's identity: the two keys `serve-demo.ts` writes and the hub serves. */
export interface Identity {
  environment_id: string;
  label: string;
}

/** The identity `serve-demo.ts` wrote into `home`, or null while there is none. */
export function readIdentity(home: string): Identity | null {
  const file = join(home, IDENTITY_FILE);
  if (!existsSync(file)) return null;
  try {
    const raw = JSON.parse(readFileSync(file, "utf8")) as Partial<Identity>;
    if (typeof raw.environment_id !== "string" || typeof raw.label !== "string") return null;
    return { environment_id: raw.environment_id, label: raw.label };
  } catch {
    return null;
  }
}

/**
 * Whether the server at `base` answers `IDENTITY_ROUTE` with exactly `want`. Any other
 * server (an `hx serve` on the real `~/.hypothex`), no server, or an error gives false.
 */
export async function answersAs(base: string, want: Identity): Promise<boolean> {
  try {
    const response = await fetch(`${base}${IDENTITY_ROUTE}`, { signal: AbortSignal.timeout(2_000) });
    if (!response.ok) return false;
    const got = (await response.json()) as Partial<Identity>;
    return got.environment_id === want.environment_id;
  } catch {
    return false;
  }
}

/** Read only this suite's fresh owner-home credential through the local CLI. Never log it. */
export function localToken(home: string): string {
  if (home !== HOME_DIR && home !== HOSTS_HOME_DIR) throw new Error("Not an isolated test home");
  const result = spawnSync("uv", ["run", "--project", REPO_ROOT, "hx", "--home", home, "token"], {
    cwd: REPO_ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
  });
  const token = result.stdout?.trim();
  if (result.status !== 0 || !token) throw new Error("Cannot read isolated test token");
  return token;
}
