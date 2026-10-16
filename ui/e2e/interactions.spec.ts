/** Read-only interactions on the task page: visibility, the Compare panel, keyboard (spec 4.2, 9). */
import { demoTask, expect, test } from "./fixtures";

test("hiding a config removes its line from every chart", async ({ page }) => {
  const { project, task } = demoTask("training");
  await page.goto(`/t/${project}/${task}`);
  const sidebar = page.getByRole("complementary", { name: "Runs" });
  const firstEye = sidebar.getByRole("button", { name: /^(Hide|Show) / }).first();
  await expect(firstEye).toHaveAttribute("aria-pressed", "true");
  const id = await firstEye.getAttribute("data-identity");
  if (!id) throw new Error("the eye has no data-identity");
  const marks = page.locator(`[data-series="${id}"]`);
  await expect.poll(() => marks.count()).toBeGreaterThan(0);
  await firstEye.click();
  await expect(firstEye).toHaveAttribute("aria-pressed", "false");
  await expect(marks).toHaveCount(0);
  await expect(page).toHaveURL(/hide=/);
  await firstEye.click();
  await expect(firstEye).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => marks.count()).toBeGreaterThan(0);
});

test("compare panel: rows are datasets, columns are runs, one dataset always stays", async ({ page }) => {
  const { project, task } = demoTask("eval_matrix");
  await page.goto(`/t/${project}/${task}`);
  const panel = page.getByRole("region", { name: /^Compare datasets/ });
  const table = panel.getByRole("table");
  const datasets = panel.getByRole("group", { name: "Datasets" });
  await expect(table.getByRole("rowheader", { name: "test-a" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: /db v4/ })).toBeVisible();
  // superseded runs are hidden by default
  await expect(table.getByRole("columnheader", { name: /db v3$/ })).toHaveCount(0);
  // the demo has three datasets, so all are selected by default (default = the first four)
  const holdout = datasets.getByRole("checkbox", { name: "holdout" });
  await expect(table.getByRole("rowheader", { name: "holdout" })).toBeVisible();
  await holdout.click();
  await expect(holdout).toHaveAttribute("aria-checked", "false");
  await expect(table.getByRole("rowheader", { name: "holdout" })).toHaveCount(0);
  await holdout.click();
  await expect(table.getByRole("rowheader", { name: "holdout" })).toBeVisible();
  for (const name of ["test-a", "test-b", "holdout"]) {
    const chip = datasets.getByRole("checkbox", { name });
    if ((await chip.getAttribute("aria-checked")) === "true") await chip.click();
  }
  await expect(datasets.getByRole("checkbox", { checked: true })).toHaveCount(1);
  await expect(table.getByRole("rowheader")).toHaveCount(1);
  await panel.getByRole("button", { name: "Bars" }).click();
  await expect(panel.locator("svg [data-series]").first()).toBeVisible();
});

test("keyboard: rows open on Enter, the eye toggles without navigating", async ({ page }) => {
  const { project, task } = demoTask("generic");
  await page.goto(`/t/${project}/${task}`);
  const sidebar = page.getByRole("complementary", { name: "Runs" });
  const eye = sidebar.getByRole("button", { name: /^(Hide|Show) / }).first();
  await expect(eye).toHaveAttribute("aria-pressed", "true");
  await eye.focus();
  await page.keyboard.press("Enter");
  await expect(eye).toHaveAttribute("aria-pressed", "false");
  await expect(page).toHaveURL(new RegExp(`/t/${project}/${task}\\?`));
  await expect(page).toHaveURL(/hide=/);
  const row = sidebar.getByRole("listitem").first();
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/r\//);
});
