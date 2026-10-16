/**
 * Docs screenshots: every v5 screen in light and dark at 1440×900, written to
 * `docs/_static/ui/{home,task,eval,runs,run,sweep}-{light,dark}.png`.
 *
 * Run it against a fresh demo hub in a /tmp home (never your own), served without a token:
 *
 *   export HYPOTHEX_HOME=/tmp/hx-shots HYPOTHEX_SSH=false HYPOTHEX_SCP=false
 *   uv run hx demo --with-hosts && uv run hx serve --port 7777 --no-auth
 *   cd ui && HX_URL=http://127.0.0.1:7777 bun scripts/screenshots.ts
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = process.env.HX_URL ?? "http://127.0.0.1:7777";
const out = new URL("../../docs/_static/ui/", import.meta.url).pathname;
mkdirSync(out, { recursive: true });

const res = await fetch(`${base}/api/v1/tasks/rxn-forward/uspto-forward-top1/runs`);
if (!res.ok) throw new Error(`GET task runs: ${res.status} (is the hub served with --no-auth?)`);
const task = (await res.json()) as {
  runs: { run_id: string; status: string }[];
  groups: { run_ids: string[]; is_best: boolean }[];
};
// a finished run of the best config, so the run page shows identity colour 1
const best = new Set(task.groups.find((g) => g.is_best)?.run_ids ?? []);
const finished = task.runs.filter((r) => r.status === "finished");
const run = finished.find((r) => best.has(r.run_id)) ?? finished[0];
if (!run) throw new Error("the demo task has no finished run");

const pages: Record<string, string> = {
  home: "/",
  task: "/t/rxn-forward/uspto-forward-top1",
  eval: "/t/eval-matrix/multi-dataset",
  runs: "/t/rxn-forward/uspto-forward-top1?tab=runs",
  run: `/r/${run.run_id}`,
  sweep: "/t/rxn-forward/uspto-forward-top1?tab=sweeps",
};

const browser = await chromium.launch();
for (const theme of ["light", "dark"] as const) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: theme });
  for (const [name, path] of Object.entries(pages)) {
    await page.goto(base + path, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}${name}-${theme}.png` });
  }
  await page.close();
}
await browser.close();
