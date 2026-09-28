import { expect, expectTheme, getJson, type OverviewLite, test } from "./fixtures";

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
