import {
  type BoardLite,
  demoTask,
  type ExampleDiffLite,
  expect,
  expectTheme,
  getJson,
  type OverviewLite,
  type PanelLite,
  postJson,
  type RunLite,
  test,
  type ViewInfoLite,
} from "./fixtures";
import { KINDS } from "./paths";

test("overview shows the headline and every demo project", async ({ page, request, theme }) => {
  const summary = await getJson<OverviewLite>(request, "/api/v1/overview");
  expect(summary.projects.length).toBeGreaterThanOrEqual(5);
  await page.goto("/");
  await expectTheme(page, theme);
  await expect(page.getByText(summary.headline).first()).toBeVisible();
  for (const row of summary.projects) {
    await expect(page.getByText(row.project).first()).toBeVisible();
  }
});

for (const kind of KINDS) {
  test(`task page renders the ${kind} preset`, async ({ page, request, theme }) => {
    const { project, task } = demoTask(kind);
    const api = `/api/v1/tasks/${project}/${task}`;
    const board = await getJson<BoardLite>(request, `${api}/leaderboard`);
    expect(board.kind).toBe(kind);
    const views = await getJson<ViewInfoLite[]>(request, `${api}/views`);
    expect(views[0]?.name).toBe("overview");
    const query = await postJson<{ panels: PanelLite[] }>(request, `${api}/views/query`, {
      name: "overview",
    });
    expect(query.panels.length).toBeGreaterThan(0);

    await page.goto(`/t/${project}/${task}`);
    await expectTheme(page, theme);
    await expect(page.getByText(board.headline).first()).toBeVisible();
    const tabs = page.getByRole("navigation", { name: "Views" });
    await expect(tabs).toBeVisible();
    for (const view of views) {
      await expect(tabs.getByRole("link", { name: view.title }).first()).toBeVisible();
    }
    await expect(tabs.locator('a[aria-current="page"]')).toContainText(views[0]?.title ?? "");
    for (const panel of query.panels) {
      if (!panel.title) continue;
      await expect(page.getByRole("heading", { name: panel.title }).first()).toBeVisible();
    }
    await expect(page.getByRole("link", { name: "+ view" })).toHaveAttribute(
      "href",
      `/t/${project}/${task}/edit/new`,
    );
  });

  test(`run page renders the ${kind} run detail`, async ({ page, request, theme }) => {
    const { project, task } = demoTask(kind);
    const runs = await getJson<RunLite[]>(
      request,
      `/api/v1/runs?project=${project}&task=${task}&status=finished&limit=1`,
    );
    const run = runs[0];
    if (!run) throw new Error(`demo ${kind} has no finished run`);
    const layout = await getJson<{ kind: string; run_view: PanelLite[] }>(
      request,
      `/api/v1/tasks/${project}/${task}/kind`,
    );
    expect(layout.kind).toBe(kind);

    // a run without traces hides the panels that read them (trace, source: traces)
    const traces = await getJson<unknown[]>(request, `/api/v1/runs/${run.run_id}/traces`);
    const readsTraces = (p: PanelLite) => p.type === "trace" || p.data?.source === "traces";

    await page.goto(`/r/${run.run_id}`);
    await expectTheme(page, theme);
    await expect(page.getByText(run.hypothesis || run.run_id).first()).toBeVisible();
    for (const panel of layout.run_view) {
      if (!panel.title) continue;
      const heading = page.getByRole("heading", { name: panel.title });
      if (traces.length === 0 && readsTraces(panel)) await expect(heading).toHaveCount(0);
      else await expect(heading.first()).toBeVisible();
    }
  });
}

test("examples page compares the two best generic groups", async ({ page, request, theme }) => {
  const { project, task } = demoTask("generic");
  const board = await getJson<BoardLite>(request, `/api/v1/tasks/${project}/${task}/leaderboard`);
  const best = board.rows[0]?.latest_run_id;
  const second = board.rows[1]?.latest_run_id;
  if (!best || !second) throw new Error("generic demo needs at least two seed groups");
  const metric = board.primary.split("/")[0] ?? board.primary;
  const diff = await getJson<ExampleDiffLite>(
    request,
    `/api/v1/compare/examples?a=${second}&b=${best}&metric=${encodeURIComponent(metric)}`,
  );
  expect(diff.broken.length).toBeGreaterThan(0);

  await page.goto(`/x/${second}/${best}?metric=${encodeURIComponent(metric)}`);
  await expectTheme(page, theme);
  await expect(page.getByText(/\bp [=<] /).first()).toBeVisible();
  // The broken ids themselves are not all visible: the errors table shows only the first 8
  // of B's failures in predictions-file order, and the strip keeps ids in SVG <title>s.
  // The headline and the 2×2 outcome table show the counts, so check those.
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    `fixes ${diff.fixed.length}, breaks ${diff.broken.length}`,
  );
  const outcomes = page.locator("table.ot");
  await expect(outcomes.locator("td.fx .n")).toHaveText(String(diff.fixed.length));
  await expect(outcomes.locator("td.bk .n")).toHaveText(String(diff.broken.length));
  await expect(outcomes.locator("td.same .n")).toHaveText([String(diff.both_pass), String(diff.both_fail)]);
});

test("view editor opens with a YAML editor and preview", async ({ page, theme }) => {
  const { project, task } = demoTask("generic");
  await page.goto(`/t/${project}/${task}/edit/new`);
  await expectTheme(page, theme);
  await expect(page.locator(".cm-editor")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeVisible();
});
