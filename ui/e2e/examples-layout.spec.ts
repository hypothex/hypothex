/** A contained page can still have an outcome table paint over the adjacent chart. */
import type { RunDetail } from "../src/api/models";
import { type BoardLite, type ExampleDiffLite, demoTask, expect, expectTheme, getJson, test } from "./fixtures";

const LABELS = {
  words: ["synthetic baseline has one wrong example", "correct synthetic error with rate 1e-4"],
  unbroken: ["baseline_configuration_123456789012345", "candidate_configuration_12345678901234"],
};

for (const [shape, labels] of Object.entries(LABELS)) {
  for (const width of [800, 1600]) {
    test(`long ${shape} Examples labels stay in their outcome panel at ${width}px`, async ({ page, request, theme }, info) => {
      const { project, task } = demoTask("generic");
      const board = await getJson<BoardLite>(request, `/api/v1/tasks/${project}/${task}/leaderboard`);
      const a = board.rows[1]?.latest_run_id;
      const b = board.rows[0]?.latest_run_id;
      if (!a || !b) throw new Error("generic demo needs two scored groups");
      const metric = board.primary.split("/")[0] ?? board.primary;
      const diff = await getJson<ExampleDiffLite>(request,
        `/api/v1/compare/examples?a=${a}&b=${b}&metric=${encodeURIComponent(metric)}`);
      // Exercise the reported label shape while retaining the demo's actual outcomes.
      for (const [index, id] of [a, b].entries()) {
        const detail = await getJson<RunDetail>(request, `/api/v1/runs/${id}`);
        await page.route(`**/api/v1/runs/${id}`, route => route.fulfill({
          json: { ...detail, record: { ...detail.record, hypothesis: labels[index] } },
        }));
      }
      await page.setViewportSize({ width, height: 1200 });
      await page.goto(`/x/${a}/${b}?metric=${encodeURIComponent(metric)}`);
      await expectTheme(page, theme);
      const outcomes = page.getByRole("region", { name: "a Outcomes", exact: true });
      const table = outcomes.locator("table.ot");
      await expect(table.locator("td.fx .n")).toHaveText(String(diff.fixed.length));
      await expect(table.locator("td.bk .n")).toHaveText(String(diff.broken.length));
      await expect(table.locator("td.same .n")).toHaveText([String(diff.both_pass), String(diff.both_fail)]);
      await expect(table.locator("thead th")).toHaveText(["", `${labels[1]} right`, `${labels[1]} wrong`]);
      await expect(table.locator("tbody th")).toHaveText([`${labels[0]} right`, `${labels[0]} wrong`]);
      await page.evaluate(() => document.fonts.ready);
      if (shape === "words") {
        const token = page.locator(".headline .nb").filter({ hasText: /^1e-4$/ });
        await expect(token).toHaveCount(1);
        expect(await token.evaluate(element => {
          const range = document.createRange();
          range.selectNodeContents(element);
          return range.getClientRects().length;
        }), "a fitting scientific token stays on one line").toBe(1);
      }
      await page.screenshot({ path: info.outputPath(`examples-${theme}-${width}.png`), fullPage: true });

      const bounds = await outcomes.evaluate(figure => {
        const box = (element: Element | DOMRect) => {
          const { left, right, top, bottom } = element instanceof Element ? element.getBoundingClientRect() : element;
          return { left, right, top, bottom };
        };
        const table = figure.querySelector("table.ot")!;
        const chart = figure.nextElementSibling!.querySelector(".signtest")!;
        const cells = Array.from(table.querySelectorAll("th, td"));
        const text = cells.flatMap(cell => {
          const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
          const rects = [];
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            if (!node.textContent?.trim()) continue;
            const range = document.createRange();
            range.selectNodeContents(node);
            for (const rect of Array.from(range.getClientRects())) rects.push({ ...box(rect), cell: box(cell), text: node.textContent });
          }
          return rects;
        });
        return { figure: box(figure), table: box(table), chart: box(chart), text };
      });
      expect(bounds.table.left).toBeGreaterThanOrEqual(bounds.figure.left - 1);
      expect(bounds.table.right, "outcomes table must stay inside its own Figure").toBeLessThanOrEqual(bounds.figure.right + 1);
      expect(bounds.table.bottom).toBeLessThanOrEqual(bounds.figure.bottom + 1);
      expect(bounds.table.right <= bounds.chart.left || bounds.chart.right <= bounds.table.left ||
        bounds.table.bottom <= bounds.chart.top || bounds.chart.bottom <= bounds.table.top,
      "outcomes must not overlap Sign test").toBe(true);
      for (const text of bounds.text) {
        expect(text.left, text.text).toBeGreaterThanOrEqual(text.cell.left - 1);
        expect(text.right, text.text).toBeLessThanOrEqual(text.cell.right + 1);
        expect(text.top, text.text).toBeGreaterThanOrEqual(text.cell.top - 1);
        expect(text.bottom, text.text).toBeLessThanOrEqual(text.cell.bottom + 1);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
        "Examples content must stay within the viewport").toBeLessThanOrEqual(0);
      const summaryText = await page.locator(".ab .nm, .ab .acc, .headline .nb").evaluateAll(elements =>
        elements.flatMap(element => {
          const container = element.closest(".ab > div") ?? element.closest(".headline")!;
          const { left, right } = container.getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(element);
          return Array.from(range.getClientRects()).map(rect => ({
            left: rect.left, right: rect.right, containerLeft: left, containerRight: right,
            text: element.textContent,
          }));
        }));
      for (const text of summaryText) {
        expect(text.left, text.text ?? "").toBeGreaterThanOrEqual(text.containerLeft - 1);
        expect(text.right, text.text ?? "").toBeLessThanOrEqual(text.containerRight + 1);
      }
    });
  }
}
