/** UI-F4: actual SVG text geometry at narrow spans, with isolated read-only fixtures. */
import type { Locator } from "@playwright/test";
import type { PanelResult, PanelSpec, ViewSpec } from "../src/api/models";
import { demoTask, expect, expectTheme, getJson, test } from "./fixtures";

type Box = { left: number; right: number; top: number; bottom: number; width: number; height: number };

async function boxes(locator: Locator): Promise<Box[]> {
  return locator.evaluateAll((elements) => elements.map((element) => {
    const { left, right, top, bottom, width, height } = element.getBoundingClientRect();
    return { left, right, top, bottom, width, height };
  }));
}

function contained(inner: Box, outer: Box): void {
  expect(inner.width).toBeGreaterThan(0);
  expect(inner.height).toBeGreaterThan(0);
  expect(inner.left).toBeGreaterThanOrEqual(outer.left - 1);
  expect(inner.right).toBeLessThanOrEqual(outer.right + 1);
  expect(inner.top).toBeGreaterThanOrEqual(outer.top - 1);
  expect(inner.bottom).toBeLessThanOrEqual(outer.bottom + 1);
}

function noOverlap(rects: Box[]): void {
  for (const [i, a] of rects.entries()) {
    for (const b of rects.slice(i + 1)) {
      expect(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top,
        `overlapping text: ${JSON.stringify({ a, b })}`).toBe(true);
    }
  }
}

const NAMES = ["cost-aware search agent one", "cost-aware search agent two", "cost-aware search agent three"];
const CATEGORIES = ["timeout", "repeated planning loop", "invalid molecular structure", "tool execution error", "gave up"];

/**
 * Deterministic tight scatter points and long legend labels, drawn by the Charts tab's kind
 * section (v5 draws the preset's leaderboard in its own Scores section, so none here).
 */
function fixtures(span: number): { panels: PanelResult[]; specs: PanelSpec[] } {
  const panels: PanelResult[] = [
    {
      type: "scatter", title: "Cost vs solved geometry",
      meta: { x: "usage.usd", y: "solved/value", x_type: "quantitative", scale: "linear", best_group: "g1", pareto: null },
      rows: NAMES.map((label, i) => ({
        group_id: `g${i + 1}`, label, x: 0.3 + i * 0.001, y: 0.6 + i * 0.001,
        x_lo: 0.1, x_hi: 0.5, y_lo: 0.4, y_hi: 0.8, seeds: [], pareto: false, regression: false,
      })),
    },
    {
      type: "vega_lite", title: "Failures geometry",
      rows: CATEGORIES.flatMap((category, i) => [
        { label: "agent one", category, failed: i + 1 },
        { label: "agent two", category, failed: i + 2 },
      ]),
      meta: { spec: {
        mark: "bar", height: { step: 30 },
        encoding: {
          y: { field: "label", type: "nominal", title: null },
          x: { field: "failed", aggregate: "sum", type: "quantitative", title: "failed attempts" },
          color: { field: "category", type: "nominal", title: null,
            legend: { orient: "bottom", columns: 3 } },
        },
      } },
    },
  ];
  return {
    panels,
    specs: panels.map((panel, i) => ({ type: panel.type, title: panel.title, layout: { span, row: i + 1 } })),
  };
}

for (const span of [5, 7, 12]) {
  test(`chart text fits span ${span} before and after resizing`, async ({ page, request, theme }) => {
    const { project, task } = demoTask("agent_eval");
    const api = `/api/v1/tasks/${project}/${task}/views`;
    const detail = await getJson<{ view: ViewSpec } & Record<string, unknown>>(request, `${api}/overview`);
    const fixture = fixtures(span);
    await page.route(`**${api}/overview`, (route) => route.fulfill({
      json: { ...detail, view: { ...detail.view, panels: fixture.specs } },
    }));
    await page.route(`**${api}/query`, (route) => route.fulfill({ json: { panels: fixture.panels } }));
    await page.setViewportSize({ width: 2000, height: 1200 });
    await page.goto(`/t/${project}/${task}`);
    await expectTheme(page, theme);
    await page.evaluate(() => document.fonts.ready);

    const scatter = page.getByRole("region", { name: "Cost vs solved geometry", exact: true });
    const failures = page.getByRole("region", { name: "Failures geometry", exact: true });
    const widths: number[] = [];
    // v5 layout widths (spec section 9): wide, narrow, wide again.
    for (const width of [2000, 1280, 2000]) {
      await page.setViewportSize({ width, height: 1200 });
      await expect(async () => {
        // v5 panels are equal cells of one grid; span 12 alone takes the whole row
        await expect(scatter).toHaveCSS("grid-column", span === 12 ? "1 / -1" : "auto");
        const plot = scatter.locator('svg[role="img"]');
        await expect(plot).toBeVisible();
        const plotBox = (await boxes(plot))[0];
        const labels = await boxes(plot.locator("[data-group] > text"));
        expect(labels).toHaveLength(NAMES.length);
        noOverlap(labels);
        labels.forEach((label) => contained(label, plotBox));
        contained(plotBox, (await boxes(scatter))[0]);
        const titles = await plot.locator("[data-group] > rect > title").allTextContents();
        for (const name of NAMES) expect(titles.some((title) => title.startsWith(name))).toBe(true);

        const container = failures.getByTestId("vega");
        await expect(container.locator(".role-legend")).toHaveCount(1);
        const containerBox = (await boxes(container))[0];
        const legend = (await boxes(container.locator(".role-legend")))[0];
        contained(legend, containerBox);
        const legendLabels = await boxes(container.locator(".role-legend-label text"));
        expect(legendLabels).toHaveLength(CATEGORIES.length);
        noOverlap(legendLabels);
        legendLabels.forEach((label) => contained(label, containerBox));
      }).toPass({ timeout: 15000 });
      widths.push((await boxes(scatter.locator('svg[role="img"]')))[0].width);
    }
    // a full-row panel narrows with the window; a grid cell may not (fewer, wider columns)
    if (span === 12) expect(widths[1]).toBeLessThan(widths[0]);
    expect(widths[2]).toBeCloseTo(widths[0], 0);
  });
}
