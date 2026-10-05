/** Browser regressions backed by the isolated demo's records; no fabricated data. */
import type { APIRequestContext, Page, TestInfo } from "@playwright/test";
import type { Leaderboard, RunDetail, RunRecord, TraceSummary, ViewQueryResult } from "../src/api/models";
import { demoTask, expect, expectTheme, getJson, postJson, test } from "./fixtures";
import { checkLayout } from "./layout-geometry";

const kinds = ["training", "agent_eval", "agent_iteration", "system_bench"] as const;
const enc = encodeURIComponent;
test.setTimeout(60_000);
async function taskData(request: APIRequestContext, kind: typeof kinds[number]) {
  const { project, task } = demoTask(kind);
  const path = `${enc(project)}/${enc(task)}`;
  const api = `/api/v1/tasks/${path}`;
  const board = await getJson<Leaderboard>(request, `${api}/leaderboard`);
  return { project, task, path, api, board };
}
async function screenshots(page: Page, info: TestInfo, name: string): Promise<void> {
  for (const width of [1600, 800]) {
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
for (const kind of kinds) {
  test(`${kind}: metric, seed visibility, inline selection and full route`, async ({ page, request, theme, authToken }, info) => {
    const { path, api, board } = await taskData(request, kind);
    await page.goto(`/t/${path}`);
    await expectTheme(page, theme);
    const metric = page.getByRole("combobox", { name: "Metric", exact: true });
    await expect(metric).toHaveValue(board.primary);
    const options = await metric.locator("option").evaluateAll(nodes => nodes.map(node => (node as HTMLOptionElement).value));
    const alternate = options.find(option => option !== board.primary);
    if (alternate) {
      const expected = await getJson<Leaderboard>(request, `${api}/leaderboard?primary=${enc(alternate)}`);
      await metric.selectOption(alternate);
      await expect(metric).toHaveValue(alternate);
      await expect(page.getByText(expected.headline, { exact: true }).first()).toBeVisible();
    } else info.annotations.push({ type: "coverage", description: `${kind} demo exposes only ${board.primary}; no alternate metric invented.` });
    const toggle = page.getByRole("checkbox", { name: kind === "system_bench" ? "Repeats" : "Seeds", exact: true });
    await expect(toggle).toBeChecked();
    const seedMarks = page.locator('.lb svg .seeds, .lb svg .identical');
    await expect(seedMarks.first()).toBeVisible();
    await toggle.uncheck();
    await expect(toggle).not.toBeChecked();
    await expect(seedMarks).toHaveCount(0);
    await toggle.check();
    await expect(toggle).toBeChecked();
    await expect(seedMarks.first()).toBeVisible();
    if (alternate) await metric.selectOption(board.primary);
    const runId = board.rows[0]!.latest_run_id;
    const detail = await getJson<RunDetail>(request, `/api/v1/runs/${enc(runId)}`);
    await page.locator(`a[href="/r/${enc(runId)}"]`).first().click();
    await expect(page).toHaveURL(new RegExp(`/t/${path}$`));
    const selected = page.getByRole("region", { name: "Selected run", exact: true });
    await expect(selected.getByRole("heading", { name: `Selected run · ${runId}` })).toBeVisible();
    await expect(selected.getByRole("heading", { name: `Selected run · ${runId}` })).toBeFocused();
    await expect(selected.getByRole("heading", { name: `Selected run · ${runId}` })).toBeInViewport();
    if (kind === "training") {
      await info.attach("training-selection-click-geometry", { body: JSON.stringify(await page.evaluate(() => {
        const pane = document.querySelector('section[aria-label="Selected run"]')!.getBoundingClientRect();
        return { pane: { top: pane.top, bottom: pane.bottom, height: pane.height }, viewportHeight: innerHeight, scrollY, activeElement: { tag: document.activeElement?.tagName, text: document.activeElement?.textContent, href: document.activeElement?.getAttribute("href") } };
      }), null, 2), contentType: "application/json" });
      // Keep the click-time measurements; let the compositor paint the long scroll
      // before capture without changing scroll, viewport, focus, or page data.
      await page.evaluate(() => new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("Selection did not reach two animation frames within 2 seconds")), 2_000);
        requestAnimationFrame(() => requestAnimationFrame(() => { clearTimeout(timeout); resolve(); }));
      }));
      await page.screenshot({ path: info.outputPath("training-selection-immediately-after-click.png") });
    }
    await expect(selected.getByText(detail.record.hypothesis || "No hypothesis recorded.", { exact: true })).toBeVisible();
    for (const name of ["Parameters", "Where", "Evaluated scores"]) await expect(selected.getByRole("heading", { name, exact: true })).toBeVisible();
    await screenshots(page, info, `${kind}-selected`);
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
      await expect(popup.getByText(detail.record.hypothesis || runId).first()).toBeVisible();
    }
    finally { await popup.close(); }
    await selected.getByRole("button", { name: "Close selected run", exact: true }).click();
    await expect(selected).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`/t/${path}$`));
  });
}

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

test("system: raw sample rows follow selected-run scope", async ({ page, request }, info) => {
  const { api, path, board } = await taskData(request, "system_bench");
  await page.goto(`/t/${path}`);
  const section = page.getByRole("region", { name: "Raw benchmark samples" });
  await expect(section.getByText("All task runs", { exact: true })).toBeVisible();
  const runId = board.rows[0]!.latest_run_id;
  const query = await postJson<ViewQueryResult>(request, `${api}/views/query`, { panel: { type: "table", title: "Raw samples", data: { source: "samples", fields: ["name", "value"], filter: { run_id: runId } } } });
  const rows = query.panels[0]!.rows.slice(0, 100);
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.every(row => row.run_id === runId)).toBe(true);
  await page.locator(`a[href="/r/${enc(runId)}"]`).first().click();
  await expect(section.getByText(`Run ${runId}`, { exact: true })).toBeVisible();
  const table = section.getByRole("table", { name: "Raw samples", exact: true });
  await expect(table.locator("tbody tr")).toHaveCount(rows.length);
  await expect(table.locator("tbody tr").first().locator("td")).toHaveText(["run_id", "seed", "name", "value"].map(key => String(rows[0]![key] ?? "unknown")));
  expect(await table.locator("tbody tr td:first-child").allTextContents()).toEqual(rows.map(row => String(row.run_id)));
  await screenshots(page, info, "system-selected-samples");
  await page.getByRole("button", { name: "Close selected run", exact: true }).click();
  await expect(section.getByText("All task runs", { exact: true })).toBeVisible();
});
