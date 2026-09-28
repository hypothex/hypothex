/** Paths and constants shared by the Playwright config, the demo server, and the specs. */
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_DIR = fileURLToPath(new URL(".", import.meta.url));
/** Fresh Hypothex home, wiped and re-seeded on every server start. */
export const HOME_DIR = join(E2E_DIR, ".home");
/** `hx demo --json` output: `{kind: "project/task"}`. */
export const DEMO_FILE = join(E2E_DIR, ".demo.json");
export const REPO_ROOT = resolve(E2E_DIR, "..", "..");
export const UI_DIST_INDEX = join(REPO_ROOT, "src", "hypothex", "ui_dist", "index.html");
export const PORT = Number(process.env.HX_E2E_PORT ?? "7788");
export const KINDS = [
  "generic",
  "training",
  "agent_eval",
  "agent_iteration",
  "system_bench",
] as const;
export type Kind = (typeof KINDS)[number];
