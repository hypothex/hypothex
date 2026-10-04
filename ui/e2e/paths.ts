/** Paths and constants shared by the Playwright config, the demo server, and the specs. */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_DIR = fileURLToPath(new URL(".", import.meta.url));
/** Fresh Hypothex home, wiped and re-seeded on every server start. */
export const HOME_DIR = join(E2E_DIR, ".home");
/** `hx demo --json` output: `{kind: "project/task"}`. */
export const DEMO_FILE = join(E2E_DIR, ".demo.json");
export const REPO_ROOT = resolve(E2E_DIR, "..", "..");
export const UI_DIST_INDEX = join(REPO_ROOT, "src", "hypothex", "ui_dist", "index.html");

/** Run by `node -e` or `bun -e`: bind port 0 on 127.0.0.1, print the port the OS gave, close. */
const FREE_PORT_JS =
  "const s = require('node:net').createServer(); s.listen(0, '127.0.0.1', () => { console.log(s.address().port); s.close(); });";

/**
 * A TCP port the OS reports free on 127.0.0.1. A child process does the bind, so this
 * stays synchronous (the Playwright config cannot await).
 */
export function freePort(): number {
  const out = spawnSync(process.execPath, ["-e", FREE_PORT_JS], { encoding: "utf8" });
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

export const KINDS = [
  "generic",
  "training",
  "agent_eval",
  "agent_iteration",
  "system_bench",
] as const;
export type Kind = (typeof KINDS)[number];

/**
 * Hub home for the `hx demo --with-hosts` server (fake remote hosts), wiped on every start.
 * `HX_E2E_HOSTS_HOME` moves it (the shutdown check uses its own home).
 */
export const HOSTS_HOME_DIR = process.env.HX_E2E_HOSTS_HOME ?? join(E2E_DIR, ".home-hosts");
/** `hx demo --with-hosts --json` output. */
export const HOSTS_DEMO_FILE = join(E2E_DIR, ".demo-hosts.json");
/**
 * Labels `serve-demo.ts` writes into each fresh demo home's `environment.json`, with a new
 * `environment_id`; every check compares both with the hub's answer before it uses the hub.
 */
export const DEMO_LABEL = "hx-e2e-demo";
export const HOSTS_DEMO_LABEL = "hx-e2e-hosts";
/** The environment identity file in a Hypothex home (`Layout.environment_json`). */
export const IDENTITY_FILE = "environment.json";
/** How long `serve-demo.ts` waits for `hx serve` to clean up after SIGTERM before SIGKILL. */
export const SHUTDOWN_WAIT_MS = 60_000;
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
    return got.environment_id === want.environment_id && got.label === want.label;
  } catch {
    return false;
  }
}
