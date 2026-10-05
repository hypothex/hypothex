import { checkLayout, LAYOUT_WIDTHS } from "./layout-geometry";
import { readFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import type { Page } from "@playwright/test";
import {
  demoTask,
  expect,
  expectTheme,
  getJson,
  type ProjectLite,
  test,
  type ViewInfoLite,
} from "./fixtures";

function viewYaml(title: string): string {
  return [
    `title: ${title}`,
    "panels:",
    "  - type: markdown",
    "    title: note",
    `    text: round trip ${title}`,
    "  - type: leaderboard",
    "    title: board",
    "",
  ].join("\n");
}

/** Replace the whole CodeMirror document in one input event (no auto-indent per key). */
async function replaceEditorText(page: Page, text: string): Promise<void> {
  await page.locator(".cm-content").click();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.insertText(text);
}

test("a view saved in the editor is written to disk and shows as a tab", async ({
  page,
  request,
  theme,
}) => {
  const { project, task } = demoTask("generic");
  const name = `e2e-${theme}`;
  const title = `e2e ${theme}`;
  const text = viewYaml(title);
  const api = `/api/v1/tasks/${project}/${task}/views/${name}`;
  try {
    await page.goto(`/t/${project}/${task}/edit/new`);
    await expectTheme(page, theme);
    await page.getByLabel(/^name$/i).fill(name);
    await replaceEditorText(page, text);
    const save = page.getByRole("button", { name: "Save", exact: true });
    await expect(save).toBeEnabled();
    const [put] = await Promise.all([
      page.waitForResponse(
        (response) => response.request().method() === "PUT" && response.url().endsWith(api),
      ),
      save.click(),
    ]);
    expect(put.status()).toBe(200);

    const stored = await getJson<{ info: ViewInfoLite; text: string }>(request, api);
    expect(stored.info).toMatchObject({ name, title, origin: "file" });
    expect(stored.text).toBe(text);
    const projects = await getJson<ProjectLite[]>(request, "/api/v1/projects");
    const repo = projects.find((p) => p.project === project)?.repo;
    if (!repo) throw new Error(`project ${project} not registered`);
    const file = join(repo, ".hypothex", "views", task, `${name}.yaml`);
    const reported = stored.info.path ?? "";
    expect(isAbsolute(reported) ? reported : join(repo, reported)).toBe(file);
    expect(readFileSync(file, "utf8")).toBe(text);

    await page.goto(`/t/${project}/${task}`);
    const tab = page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: title });
    await expect(tab).toBeVisible();
    await tab.click();
    await expect(tab).toHaveAttribute("aria-current", "page");
    await expect(page).toHaveURL(new RegExp(`[?&]view=${name}(&|$)`));
    await expect(page.getByText(`round trip ${title}`)).toBeVisible();
  } finally {
    await request.delete(api);
  }
});

test("an invalid view blocks Save and is never written", async ({ page, request, theme }) => {
  const { project, task } = demoTask("generic");
  const name = `e2e-bad-${theme}`;
  await page.goto(`/t/${project}/${task}/edit/new`);
  await expectTheme(page, theme);
  await page.getByLabel(/^name$/i).fill(name);
  await replaceEditorText(page, ["title: bad", "panels:", "  - type: leaderbord", ""].join("\n"));
  await expect(page.locator(".cm-lint-marker-error").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  const views = await getJson<ViewInfoLite[]>(request, `/api/v1/tasks/${project}/${task}/views`);
  expect(views.map((v) => v.name)).not.toContain(name);
});

test("step7 editor geometry with actual leaderboard preview", async ({ page, theme }, info) => {
  const { project, task } = demoTask("generic");
  await page.goto(`/t/${project}/${task}/edit/new`);
  await expectTheme(page, theme);
  await replaceEditorText(page, "title: Layout preview\npanels:\n  - type: leaderboard\n    title: Large leaderboard\n    layout:\n      span: 12\n");
  await expect(page.locator(".hx-ed-pp .forest")).toBeVisible();
  for (const width of LAYOUT_WIDTHS) {
    await checkLayout(page, info, "editor", width, [".hx-ed-top", ".hx-ed-act", ".hx-ed-split", ".hx-ed-pv", ".hx-ed-pp", ".hx-ed-pv .fplot"]);
    if (width <= 1100) {
      expect.soft(await page.locator(".hx-ed-pv").evaluate((element) => getComputedStyle(element).position)).toBe("static");
    }
  }
});
