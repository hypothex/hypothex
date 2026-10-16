/** Real demo records, with chart responses held to exercise asynchronous layout growth. */
import type { RunRecord } from "../src/api/models";
import { demoTask, expect, getJson, test } from "./fixtures";

for (const userScrolls of [false, true]) {
  test(`selected run: delayed charts ${userScrolls ? "respect manual scrolling" : "keep the focused heading visible"}`, async ({ page, request }, info) => {
    const { project, task } = demoTask("training");
    const path = `${encodeURIComponent(project)}/${encodeURIComponent(task)}`;
    const runs = await getJson<RunRecord[]>(request, `/api/v1/runs?project=${encodeURIComponent(project)}&task=${encodeURIComponent(task)}&limit=1`);
    const runId = runs[0]!.run_id;
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let stepMetricsHeld = false;
    await page.route("**/api/v1/tasks/**/views/query", async route => {
      const response = await route.fetch();
      if (route.request().postDataJSON()?.view?.title === "Step metrics") stepMetricsHeld = true;
      await gate;
      await route.fulfill({ response });
    });
    try {
      await page.goto(`/t/${path}`);
      const table = page.getByRole("table", { name: "Training runs", exact: true });
      await expect(table).toBeVisible();
      await expect.poll(() => stepMetricsHeld).toBe(true);
      await table.locator(`a[href="/r/${encodeURIComponent(runId)}"]`).first().click();
      const selected = page.getByRole("region", { name: "Selected run", exact: true });
      const heading = selected.getByRole("heading", { name: `Selected run · ${runId}` });
      await expect(heading).toBeFocused();
      await expect(heading).toBeInViewport();
      const geometry = () => heading.evaluate(node => ({
        top: node.getBoundingClientRect().top,
        scroll: document.querySelector(".app-page")!.scrollTop,
        height: document.querySelector(".app-page")!.scrollHeight,
        focused: document.activeElement === node,
      }));
      const before = await geometry();
      if (userScrolls) {
        await page.mouse.move(800, 400);
        await page.mouse.wheel(0, -600);
        await expect.poll(async () => (await geometry()).scroll).toBeLessThan(before.scroll - 300);
      }
      release();
      // Drain active handlers before ending the test; no aborted route.fetch and
      // no ignored network errors can turn this regression into another flake.
      await page.unrouteAll({ behavior: "wait" });
      await expect(page.locator('.task-page [aria-busy="true"]')).toHaveCount(0);
      await expect.poll(async () => (await geometry()).height).toBeGreaterThan(before.height + 700);
      await expect(heading).toBeFocused();
      if (userScrolls) await expect(heading).not.toBeInViewport();
      else await expect(heading).toBeInViewport();
      await info.attach("selected-run-layout", { body: JSON.stringify({ before, after: await geometry(), userScrolls }, null, 2), contentType: "application/json" });
    } finally {
      release();
      await page.unrouteAll({ behavior: "wait" });
    }
  });
}
