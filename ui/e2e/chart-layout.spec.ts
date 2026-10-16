/**
 * Spec section 9 layout checks: every screen without page overflow at the v5 layout widths,
 * chart text at a constant pixel size whatever the window width, and chart text that fits
 * narrow and wide panels (UI-F4, isolated read-only fixtures).
 */
import type { APIRequestContext, Locator, Page } from "@playwright/test";
import type { PanelResult, PanelSpec, ViewSpec } from "../src/api/models";
import { demoTask, expect, expectTheme, getJson, type TaskRunsLite, test } from "./fixtures";
import { checkLayout, LAYOUT_REGIONS, LAYOUT_WIDTHS, measureLayout } from "./layout-geometry";

function taskUrl(kind: "training" | "eval_matrix", tab?: string): string {
  const { project, task } = demoTask(kind);
  return `/t/${project}/${task}${tab ? `?tab=${tab}` : ""}`;
}

async function scoredRunUrl(request: APIRequestContext): Promise<string> {
  const { project, task } = demoTask("training");
  const data = await getJson<TaskRunsLite>(request, `/api/v1/tasks/${project}/${task}/runs`);
  const run = data.runs.find((r) => !r.archived && r.primary !== null);
  if (!run) throw new Error("training demo has no scored run");
  return `/r/${run.run_id}`;
}

interface Screen {
  name: string;
  url: (request: APIRequestContext) => string | Promise<string>;
  /** Visible once the screen has loaded its data, so the check never measures a spinner. */
  ready: (page: Page) => Locator;
}

const SCREENS: Screen[] = [
  { name: "home", url: () => "/", ready: (page) => page.getByRole("heading", { name: "Recent runs" }) },
  { name: "task-training", url: () => taskUrl("training"), ready: (page) => page.locator("[data-panel] svg").first() },
  { name: "task-eval", url: () => taskUrl("eval_matrix"), ready: (page) => page.getByRole("region", { name: "Scores", exact: true }) },
  { name: "runs-table", url: () => taskUrl("training", "runs"), ready: (page) => page.getByRole("table", { name: "Runs" }) },
  { name: "sweeps", url: () => taskUrl("training", "sweeps"), ready: (page) => page.getByRole("tab", { name: /^Sweeps/, selected: true }) },
  { name: "run", url: scoredRunUrl, ready: (page) => page.getByRole("complementary", { name: "Properties" }) },
];

for (const screen of SCREENS) {
  test(`${screen.name}: no overflow at ${LAYOUT_WIDTHS.join("/")}`, async ({ page, request, theme }, info) => {
    await page.goto(await screen.url(request));
    await expectTheme(page, theme);
    await expect(screen.ready(page)).toBeVisible();
    for (const width of LAYOUT_WIDTHS) {
      await checkLayout(page, info, screen.name, width, LAYOUT_REGIONS);
    }
  });
}

// The page scrolls in `main.app-page`, not the document: a screen whose only checked regions
// are tables (home, hosts, queue) must still fail when that scroller overflows.
test("layout check catches page overflow on a screen of tables", async ({ page, theme }) => {
  await page.goto("/");
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { name: "Recent runs" })).toBeVisible();
  const clean = await measureLayout(page, 1280, LAYOUT_REGIONS);
  expect(clean.overflowing).toEqual([]);
  await page.addStyleTag({ content: ".home { min-width: 1600px; }" });
  const wide = await measureLayout(page, 1280, LAYOUT_REGIONS);
  expect(wide.overflowing.map((frame) => frame.frame)).toContain("main.app-page");
});

test("chart text does not grow with the window", async ({ page, theme }) => {
  await page.goto(taskUrl("training"));
  await expectTheme(page, theme);
  const text = page.locator("[data-panel] svg text").first();
  const sizes: number[] = [];
  for (const width of LAYOUT_WIDTHS) {
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForTimeout(250);
    sizes.push(await text.evaluate((el) => el.getBoundingClientRect().height));
  }
  expect(Math.max(...sizes) - Math.min(...sizes), `text heights ${sizes.join(", ")}`).toBeLessThan(1.5);
});

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

/** Items per visual row of the children of `selector`: a child starts a new row when it is below the current row's bottom. */
async function rowsOf(page: Page, selector: string): Promise<number[][]> {
  return page.locator(selector).evaluateAll((sets) =>
    sets.map((set) => {
      const boxes = Array.from(set.children).map((c) => c.getBoundingClientRect()).filter((b) => b.width > 0).sort((a, b) => a.top - b.top);
      const rows: number[] = [];
      let bottom = Number.NEGATIVE_INFINITY;
      for (const box of boxes) {
        if (box.top >= bottom - 1) {
          rows.push(1);
          bottom = box.bottom;
        } else {
          rows[rows.length - 1] = (rows[rows.length - 1] ?? 0) + 1;
          bottom = Math.max(bottom, box.bottom);
        }
      }
      return rows;
    }),
  );
}

// spec 4.2: the panel toolbar wraps under ~1300 px; at 1440 it fits one row (mockup #workspace)
for (const kind of ["training", "system_bench"] as const) {
  test(`${kind}: the Charts toolbar fits one row at 1440 and keeps its buttons together`, async ({ page, theme }) => {
    const { project, task } = demoTask(kind);
    await page.goto(`/t/${project}/${task}`);
    await expectTheme(page, theme);
    await expect(page.getByRole("button", { name: "Save as view" })).toBeVisible();
    for (const width of LAYOUT_WIDTHS) {
      await page.setViewportSize({ width, height: 1000 });
      await page.waitForTimeout(150);
      const [rows] = await rowsOf(page, ".task-page .ptools");
      if (width >= 1440) expect(rows, `toolbar rows at ${width}`).toHaveLength(1);
      const panel = await page.getByRole("button", { name: /Panel/ }).first().boundingBox();
      const save = await page.getByRole("button", { name: "Save as view" }).boundingBox();
      expect(Math.round(panel?.y ?? -1), `+ Panel and Save as view on one row at ${width}`).toBe(Math.round(save?.y ?? -2));
    }
  });
}
