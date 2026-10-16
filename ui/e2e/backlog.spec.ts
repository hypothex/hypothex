/** Browser regressions backed by the isolated demo's records; no fabricated data. */
import type { APIRequestContext, Page, TestInfo } from "@playwright/test";
import type { Leaderboard, RunDetail, RunRecord, TraceSummary, ViewQueryResult } from "../src/api/models";
import { demoTask, expect, expectTheme, getJson, postJson, test } from "./fixtures";
import { checkLayout } from "./layout-geometry";

type Kind = "training" | "agent_eval" | "agent_iteration" | "system_bench";
const enc = encodeURIComponent;
test.setTimeout(60_000);
async function taskData(request: APIRequestContext, kind: Kind) {
  const { project, task } = demoTask(kind);
  const path = `${enc(project)}/${enc(task)}`;
  const api = `/api/v1/tasks/${path}`;
  const board = await getJson<Leaderboard>(request, `${api}/leaderboard`);
  return { project, task, path, api, board };
}
async function screenshots(page: Page, info: TestInfo, name: string): Promise<void> {
  // v5 layout widths (spec section 9).
  for (const width of [1280, 2000]) {
    await checkLayout(page, info, name, width, ['main', 'section[aria-label="Selected run"]', '[aria-label="Key"]', '.hx-chart']);
    const geometry = await page.evaluate(() => {
      const box = (node: Element) => { const r = node.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }; };
      return Array.from(document.querySelectorAll('[aria-label="Key"]')).map(key => ({ bounds: box(key), children: Array.from(key.children).map(node => ({ text: node.textContent, ...box(node) })) }));
    });
    await info.attach(`${name}-${width}-legend-bounds`, { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
    for (const key of geometry) {
      for (const child of key.children) {
        expect.soft(child.left, `key left: ${child.text}`).toBeGreaterThanOrEqual(key.bounds.left - 2);
        expect.soft(child.right, `key right: ${child.text}`).toBeLessThanOrEqual(key.bounds.right + 2);
      }
      for (let i = 0; i < key.children.length; i++) for (const b of key.children.slice(i + 1)) {
        const a = key.children[i]!;
        expect.soft(Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1, `overlapping key entries: ${a.text} / ${b.text}`).toBe(false);
      }
    }
  }
}
test("training: inline run selection opens the full run in a new tab", async ({ page, request, theme, authToken }, info) => {
  const { project, task, path } = await taskData(request, "training");
  const runs = await getJson<RunRecord[]>(request, `/api/v1/runs?project=${enc(project)}&task=${enc(task)}&limit=1`);
  const runId = runs[0]?.run_id;
  if (!runId) throw new Error("training demo has no run");
  const detail = await getJson<RunDetail>(request, `/api/v1/runs/${enc(runId)}`);
  await page.goto(`/t/${path}`);
  await expectTheme(page, theme);
  const table = page.getByRole("table", { name: "Training runs", exact: true });
  await table.locator(`a[href="/r/${enc(runId)}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`/t/${path}$`));
  const selected = page.getByRole("region", { name: "Selected run", exact: true });
  const heading = selected.getByRole("heading", { name: `Selected run · ${runId}` });
  await expect(heading).toBeVisible();
  await expect(heading).toBeFocused();
  await expect(heading).toBeInViewport();
  await expect(selected.getByText(detail.record.hypothesis || "No hypothesis recorded.", { exact: true })).toBeVisible();
  for (const name of ["Parameters", "Where", "Evaluated scores"]) await expect(selected.getByRole("heading", { name, exact: true })).toBeVisible();
  await screenshots(page, info, "training-selected");
  const open = selected.getByRole("link", { name: "Open run ↗", exact: true });
  await expect(open).toHaveAttribute("href", `/r/${enc(runId)}`);
  const opened = page.waitForEvent("popup");
  await open.click();
  const popup = await opened;
  try {
    await expect(popup).toHaveURL(new RegExp(`/r/${enc(runId)}$`));
    // noopener opens an independent sessionStorage; authenticate that tab normally.
    await popup.getByLabel("Token", { exact: true }).fill(authToken);
    await popup.getByRole("button", { name: "Unlock", exact: true }).click();
    await expect(popup.getByRole("heading", { level: 1 })).toBeVisible();
  }
  finally { await popup.close(); }
  await selected.getByRole("button", { name: "Close selected run", exact: true }).click();
  await expect(selected).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`/t/${path}$`));
});

test("training: checkpoint metrics and evaluated scores preserve recorded provenance", async ({ page, request }, info) => {
  const { project, task, path } = await taskData(request, "training");
  const runs = await getJson<RunRecord[]>(request, `/api/v1/runs?project=${enc(project)}&task=${enc(task)}&limit=20`);
  await page.goto(`/t/${path}`);
  const table = page.getByRole("table", { name: "Training runs", exact: true });
  await expect(table.locator("tbody tr")).toHaveCount(runs.length);
  for (const name of ["Top1 best (evaluated)", "Top1 final (evaluated)"]) await expect(table.getByRole("columnheader", { name, exact: true })).toBeVisible();
  const run = runs.find(record => record.artifacts.some(artifact => artifact.kind === "checkpoint"));
  expect(run, "demo should contain recorded checkpoints").toBeDefined();
  await table.locator(`a[href="/r/${enc(run!.run_id)}"]`).click();
  const selected = page.getByRole("region", { name: "Selected run", exact: true });
  const checkpoints = run!.artifacts.filter(artifact => artifact.kind === "checkpoint");
  const names = [...new Set(checkpoints.flatMap(artifact => Object.keys(artifact.metrics)))].sort();
  const checkpointTable = selected.getByRole("table", { name: "Checkpoint metrics", exact: true });
  await expect(checkpointTable.locator("thead th")).toHaveText(["Step", "Path", ...names]);
  for (let i = 0; i < checkpoints.length; i++) {
    const artifact = checkpoints[i]!;
    await expect(checkpointTable.locator("tbody tr").nth(i).locator("td")).toHaveText([artifact.step == null ? "—" : String(artifact.step), `${artifact.host ? `${artifact.host}:` : ""}${artifact.path}`, ...names.map(name => typeof artifact.metrics[name] === "number" ? String(artifact.metrics[name]) : "—")]);
  }
  await expect(selected.getByText("Recorded checkpoint metrics; val/* are validation measurements. Run-level evaluated scores are shown separately.")).toBeVisible();
  const detail = await getJson<RunDetail>(request, `/api/v1/runs/${enc(run!.run_id)}`);
  for (const key of ["value", "final"]) {
    const score = detail.scores.filter(score => score.metric === "top1" && score.key === key).sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    if (score && score.error === null && score.value !== null) {
      const row = table.locator("tbody tr").filter({ has: page.locator(`a[href="/r/${enc(run!.run_id)}"]`) });
      await expect(row.locator(`td[title="top1@${score.version}/${key}"]`)).toHaveText(String(score.value));
    }
  }
  await screenshots(page, info, "training-record-provenance");
});

for (const kind of ["agent_eval", "agent_iteration"] as const) {
  test(`${kind}: trajectory first, exact selected example and current group`, async ({ page, request }, info) => {
    const { project, task, board } = await taskData(request, kind);
    const runs = await getJson<RunRecord[]>(request, `/api/v1/runs?project=${enc(project)}&task=${enc(task)}&limit=100`);
    let traced: { run: RunRecord; traces: TraceSummary[] } | undefined;
    for (const run of runs) {
      const traces = await getJson<TraceSummary[]>(request, `/api/v1/runs/${enc(run.run_id)}/traces`);
      if (traces.length) { traced = { run, traces }; break; }
    }
    expect(traced, "real demo run with a trace").toBeDefined();
    const { run, traces } = traced!;
    const chosen = (traces.find(trace => trace.failed) ?? traces[0])!.example_id;
    const group = board.rows.find(row => row.run_ids.includes(run.run_id));
    expect(group).toBeDefined();
    await page.goto(`/r/${enc(run.run_id)}`);
    const picker = page.getByRole("navigation", { name: "Traced examples" });
    await expect(picker.getByRole("link", { name: chosen, exact: true })).toHaveAttribute("aria-current", "true");
    const grid = page.locator('svg[aria-label^="Share of seeds solved for 1 items"]');
    await expect(grid).toBeVisible();
    await expect(grid.locator('g[data-current="true"]')).toHaveCount(1);
    await expect(grid.locator('g[data-current="true"]')).toHaveAttribute("data-group", group!.group_id);
    const items = await grid.locator("rect[data-item]").evaluateAll(nodes => nodes.map(node => node.getAttribute("data-item")));
    expect(items.length).toBeGreaterThan(0);
    expect(new Set(items)).toEqual(new Set([chosen]));
    expect((await picker.boundingBox())!.y).toBeLessThan((await grid.boundingBox())!.y);
    await picker.getByRole("link", { name: chosen, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`example=${enc(chosen)}`));
    await expect(grid.locator('g[data-current="true"] rect')).toHaveAttribute("data-item", chosen);
    await screenshots(page, info, `${kind}-selected-example`);
  });
}

test("iteration: selectors show measured outcomes or explicit missing fingerprints", async ({ page, request }, info) => {
  const { path, board } = await taskData(request, "agent_iteration");
  await page.goto(`/t/${path}`);
  const section = page.getByRole("region", { name: "Iteration example changes" });
  const earlier = section.getByRole("combobox", { name: "Earlier version / group" });
  const later = section.getByRole("combobox", { name: "Later version / group" });
  await expect(earlier).toHaveValue(board.rows[1]!.group_id);
  await expect(later).toHaveValue(board.rows[0]!.group_id);
  await expect(earlier.locator("option")).toHaveText(board.rows.map(row => row.label));
  const details = await Promise.all(board.rows.slice(0, 2).map(row => getJson<RunDetail>(request, `/api/v1/runs/${enc(row.latest_run_id)}`)));
  if (details.some(detail => !detail.record.datasets.length || detail.record.datasets.some(dataset => !dataset.hash))) {
    await expect(section.getByRole("status")).toHaveText("Incompatible comparison: dataset fingerprint is unknown.");
    await expect(section.getByRole("img")).toHaveCount(0);
    info.annotations.push({ type: "coverage", description: "Demo fingerprints missing; explicit unknown verified. Compatible waffle has deterministic unit coverage." });
  } else {
    const metric = board.primary.split("/")[0]!;
    const diff = await getJson<{ fixed: string[]; broken: string[]; both_pass: number; both_fail: number }>(request, `/api/v1/compare/examples?a=${enc(board.rows[1]!.latest_run_id)}&b=${enc(board.rows[0]!.latest_run_id)}&metric=${enc(`${metric}@${board.metric_versions[metric]}`)}`);
    const total = diff.fixed.length + diff.broken.length + diff.both_pass + diff.both_fail;
    await expect(section.getByRole("img", { name: `Example outcomes: ${diff.fixed.length} fixed, ${diff.broken.length} broken, ${total} shared` })).toBeVisible();
  }
  await earlier.selectOption(board.rows[0]!.group_id);
  await expect(section.getByText("Select two different groups.")).toBeVisible();
  await earlier.selectOption(board.rows[1]!.group_id);
  await screenshots(page, info, "iteration-comparison");
});

test("system: raw samples list the samples of every task run", async ({ page, request }, info) => {
  const { api, path } = await taskData(request, "system_bench");
  const query = await postJson<ViewQueryResult>(request, `${api}/views/query`, { panel: { type: "table", title: "Raw samples", data: { source: "samples", fields: ["name", "value"] } } });
  const rows = query.panels[0]!.rows.slice(0, 100);
  expect(rows.length).toBeGreaterThan(0);
  await page.goto(`/t/${path}`);
  const section = page.getByRole("region", { name: "Raw benchmark samples", exact: true });
  await expect(section.getByText("All task runs", { exact: true })).toBeVisible();
  const table = section.getByRole("table", { name: "Raw samples", exact: true });
  await expect(table.locator("tbody tr")).toHaveCount(rows.length);
  await expect(table.locator("tbody tr").first().locator("td")).toHaveText(["run_id", "seed", "name", "value"].map(key => String(rows[0]![key] ?? "unknown")));
  await screenshots(page, info, "system-samples");
});
