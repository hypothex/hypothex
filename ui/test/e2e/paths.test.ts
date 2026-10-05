import { afterAll, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { rmSync } from "node:fs";
import { join, resolve } from "node:path";

const UI = resolve(import.meta.dir, "..", "..");
const PRINT =
  "const m = await import('./e2e/paths.ts'); console.log(JSON.stringify({ run: m.RUN_DIR, runs: m.RUNS_DIR, homes: [m.HOME_DIR, m.HOSTS_HOME_DIR, m.DEMO_FILE, m.HOSTS_DEMO_FILE] }));";
const made: string[] = [];

/** Load `e2e/paths.ts` in a fresh process, as the Playwright runner or `shutdown-check.ts` does. */
function load(env: Record<string, string | undefined> = {}) {
  const clean = { ...process.env, HX_E2E_RUN_DIR: undefined, ...env };
  const out = spawnSync("bun", ["-e", PRINT], { cwd: UI, encoding: "utf8", env: clean });
  if (out.status === 0) {
    const got = JSON.parse(out.stdout) as { run: string; runs: string; homes: string[] };
    made.push(got.run);
    return { ok: true as const, ...got };
  }
  return { ok: false as const, stderr: out.stderr };
}

afterAll(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

test("two runs in one checkout get two directories, and every home and demo file is inside its own", () => {
  const a = load();
  const b = load();
  if (!a.ok || !b.ok) throw new Error("paths.ts did not load");
  expect(a.run).not.toBe(b.run);
  for (const got of [a, b]) {
    expect(got.run.startsWith(`${got.runs}/`)).toBe(true);
    for (const path of got.homes) expect(path.startsWith(`${got.run}/`)).toBe(true);
  }
});

test("a child given the run's directory uses it, so workers and web servers agree", () => {
  const a = load();
  if (!a.ok) throw new Error("paths.ts did not load");
  const child = load({ HX_E2E_RUN_DIR: a.run });
  expect(child.ok && child.run).toBe(a.run);
});

test("a run directory outside e2e/.runs is refused (it would be wiped)", () => {
  const out = load({ HX_E2E_RUN_DIR: join(UI, "src") });
  expect(out.ok).toBe(false);
  if (!out.ok) expect(out.stderr).toContain("HX_E2E_RUN_DIR");
});
