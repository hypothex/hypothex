/** Every v5 screen renders against the `hx demo` hub, in the light and dark projects. */
import {
  type BoardLite,
  demoTask,
  type ExampleDiffLite,
  expect,
  expectTheme,
  getJson,
  type OverviewLite,
  type TaskRunsLite,
  test,
} from "./fixtures";
import { EXTRAS, KINDS } from "./paths";

/** The v4 label shape `<group8>@<commit7>` (spec section 1); B11's ` · @<commit7>` suffix is allowed. */
const HASH_LABEL = /\b[0-9a-f]{8}@([0-9a-f]{7}|nogit)\b/;
/** Runs tagged this are hidden from the sidebar by default (spec 4.2). */
const SUPERSEDED = "superseded";

test("home lists running work, tasks and recent runs", async ({ page, request, theme }) => {
  const summary = await getJson<OverviewLite>(request, "/api/v1/overview");
  expect(summary.projects.length).toBeGreaterThanOrEqual(KINDS.length);
  await page.goto("/");
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent runs" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Navigation" });
  for (const row of summary.projects) {
    await expect(nav.getByText(row.project, { exact: true }).first()).toBeVisible();
  }
});

for (const kind of [...KINDS, ...EXTRAS]) {
  test(`task ${kind}: sidebar names every group and charts render`, async ({ page, request, theme }) => {
    const { project, task } = demoTask(kind);
    const data = await getJson<TaskRunsLite>(request, `/api/v1/tasks/${project}/${task}/runs`);
    const tags = new Map(data.runs.map((r) => [r.run_id, r.tags]));
    const shown = data.groups.filter((g) => !g.run_ids.every((id) => tags.get(id)?.includes(SUPERSEDED)));
    expect(shown.length).toBeGreaterThan(0);
    await page.goto(`/t/${project}/${task}`);
    await expectTheme(page, theme);
    const sidebar = page.getByRole("complementary", { name: "Runs" });
    for (const group of shown.slice(0, 8)) {
      await expect(sidebar.getByText(group.name, { exact: true }).first()).toBeVisible();
    }
    await expect(sidebar.getByText(HASH_LABEL)).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Scores", exact: true })).toBeVisible();
    await page.getByRole("tablist", { name: "Task" }).getByRole("tab", { name: /^Runs/ }).click();
    await expect(page).toHaveURL(/tab=runs/);
    await expect(page.getByRole("table", { name: "Runs" })).toBeVisible();
  });
}

test("run page shows scores, rank strip and properties", async ({ page, request, theme }) => {
  const { project, task } = demoTask("training");
  const data = await getJson<TaskRunsLite>(request, `/api/v1/tasks/${project}/${task}/runs`);
  const run = data.runs.find((r) => !r.archived && r.primary !== null);
  if (!run) throw new Error("training demo has no scored run");
  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(run.name);
  // the status pill's word takes the pill colour, like its glyph (mockup #run)
  const pill = page.locator(".run-page .pill").first();
  await expect(pill).toBeVisible();
  const colours = await pill.evaluate((el) => [el, el.querySelector(".st"), el.querySelector("svg")].map((n) => (n ? getComputedStyle(n).color : null)));
  expect(new Set(colours).size, `pill, word and glyph colours ${colours.join(" / ")}`).toBe(1);
  await expect(page.getByRole("region", { name: "Scores", exact: true })).toBeVisible();
  await expect(page.getByText("Where it ranks", { exact: true })).toBeVisible();
  const props = page.getByRole("complementary", { name: "Properties" });
  for (const label of ["Status", "Launcher", "Host", "Started", "Commit"]) {
    await expect(props.getByText(label, { exact: true })).toBeVisible();
  }
  const tabs = page.getByRole("tablist", { name: "Run" });
  await tabs.getByRole("tab", { name: "Charts" }).click();
  await expect(page).toHaveURL(/tab=charts/);
  await tabs.getByRole("tab", { name: "Logs" }).click();
  await expect(page).toHaveURL(/tab=logs/);
});

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
  const facts = page.locator(".examples-page .ph .facts");
  await expect(facts.getByText(`fixes ${diff.fixed.length}`, { exact: true })).toBeVisible();
  await expect(facts.getByText(`breaks ${diff.broken.length}`, { exact: true })).toBeVisible();
  await expect(facts.getByText(/^p [=<] /)).toBeVisible();
  const outcomes = page.getByRole("region", { name: "Outcomes", exact: true }).locator("table.ot");
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
