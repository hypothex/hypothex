/**
 * Playwright `webServer` command: seed a fresh demo home, then serve it.
 *
 * Wipes `e2e/.home`, runs `hx demo --json` into it, writes the kind → "project/task" map
 * to `e2e/.demo.json`, then runs `hx serve` in the foreground until Playwright stops it.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { DEMO_FILE, HOME_DIR, PORT, REPO_ROOT, UI_DIST_INDEX } from "./paths";

if (!existsSync(UI_DIST_INDEX)) {
  console.error(`missing ${UI_DIST_INDEX}: run "bun run build" in ui/ first`);
  process.exit(1);
}
rmSync(HOME_DIR, { recursive: true, force: true });
mkdirSync(HOME_DIR, { recursive: true });

const hx = ["run", "--project", REPO_ROOT, "hx", "--home", HOME_DIR];
const seeded = spawnSync("uv", [...hx, "demo", "--json"], {
  cwd: REPO_ROOT,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "inherit"],
});
if (seeded.status !== 0) {
  console.error(`hx demo failed with exit code ${seeded.status}`);
  process.exit(1);
}
writeFileSync(DEMO_FILE, seeded.stdout);

const server = spawn("uv", [...hx, "serve", "--port", String(PORT)], {
  cwd: REPO_ROOT,
  stdio: "inherit",
});
const stop = (): void => {
  server.kill("SIGTERM");
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
server.on("exit", (code) => process.exit(code ?? 0));
