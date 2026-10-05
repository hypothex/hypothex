/** UI-F4: actual SVG text geometry at narrow spans, with isolated read-only fixtures. */
import type { Locator } from "@playwright/test";
import type { PanelResult, PanelSpec, ViewQueryResult, ViewSpec } from "../src/api/models";
import { demoTask, expect, expectTheme, getJson, postJson, test } from "./fixtures";

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

/** Keep the preset's leaderboard; deterministic tight scatter points and long legend labels. */
function fixtures(source: ViewQueryResult, span: number): { panels: PanelResult[]; specs: PanelSpec[] } {
  const leaderboard = source.panels.find((panel) => panel.type === "leaderboard");
  if (!leaderboard || leaderboard.rows.length < 2) throw new Error("agent_eval demo needs a scored leaderboard");
  const panels: PanelResult[] = [
    { ...leaderboard, title: "Leaderboard geometry" },
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
    const original = await postJson<ViewQueryResult>(request, `${api}/query`, { name: "overview" });
    const fixture = fixtures(original, span);
    await page.route(`**${api}/overview`, (route) => route.fulfill({
      json: { ...detail, view: { ...detail.view, panels: fixture.specs } },
    }));
    await page.route(`**${api}/query`, (route) => route.fulfill({ json: { panels: fixture.panels } }));
    await page.setViewportSize({ width: 1600, height: 1200 });
    await page.goto(`/t/${project}/${task}`);
    await expectTheme(page, theme);
    await page.evaluate(() => document.fonts.ready);

    const board = page.getByRole("region", { name: "a Leaderboard geometry", exact: true });
    const scatter = page.getByRole("region", { name: "b Cost vs solved geometry", exact: true });
    const failures = page.getByRole("region", { name: "c Failures geometry", exact: true });
    const widths: number[] = [];
    const tickCounts: number[] = [];
    for (const width of [1600, 1120, 1600]) {
      await page.setViewportSize({ width, height: 1200 });
      await expect(async () => {
        await expect(board).toHaveCSS("grid-column", `span ${span}`);
        const axis = board.locator(".axisrow svg");
        await expect(axis).toBeVisible();
        const axisBox = (await boxes(axis))[0];
        const ticks = await boxes(board.locator(".axis-b .tk"));
        expect(ticks.length).toBeGreaterThanOrEqual(2);
        noOverlap(ticks);
        ticks.forEach((tick) => contained(tick, axisBox));
        contained(axisBox, (await boxes(board))[0]);
        for (const row of await board.locator(".frow[data-row]").all()) {
          const rowBox = (await boxes(row))[0];
          const metaBox = (await boxes(row.locator(".meta")))[0];
          expect(rowBox.height).toBeGreaterThanOrEqual(105);
          expect(metaBox.bottom).toBeLessThanOrEqual(rowBox.bottom + 1);
        }

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
      widths.push((await boxes(board.locator(".axisrow svg")))[0].width);
      tickCounts.push(await board.locator(".axis-b .tk").count());
    }
    expect(widths[1]).toBeLessThan(widths[0]);
    expect(widths[2]).toBeCloseTo(widths[0], 0);
    expect(tickCounts[1]).toBeLessThanOrEqual(tickCounts[0]);
    expect(tickCounts[2]).toBe(tickCounts[0]);
  });
}
