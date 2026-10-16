import type { Page, TestInfo } from "@playwright/test";
import { expect } from "./fixtures";

/** v5 layout widths (spec section 9); screenshots at the narrowest and the widest. */
export const LAYOUT_WIDTHS = [1280, 1440, 2000] as const;
/** Regions of a v5 screen whose shown part must stay inside the viewport. */
export const LAYOUT_REGIONS = ["[data-panel]", "table", "nav", "aside"];

/** Rendered bounds of one checked region; `shown*` is its box cut by every clipping ancestor. */
export interface RegionBounds {
  selector: string; text: string | undefined; left: number; right: number;
  shownLeft: number; shownRight: number; width: number; height: number; display: string;
}

/** What `measureLayout` reads from the page. */
export interface LayoutGeometry {
  viewport: number;
  scrollWidth: number;
  elements: RegionBounds[];
  /** Frames that overflow sideways and count as page overflow (see `checkLayout`). */
  overflowing: { frame: string; scrollWidth: number; clientWidth: number }[];
}

/** Resize to `width` and measure the viewport, each checked region and the frames that overflow. */
export async function measureLayout(page: Page, width: number, selectors: string[]): Promise<LayoutGeometry> {
  await page.setViewportSize({ width, height: 1000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);
  return page.evaluate((selectors) => {
    const root = document.documentElement;
    const clips = (element: Element): boolean => getComputedStyle(element).overflowX !== "visible";
    const label = (element: Element): string => `${element.tagName.toLowerCase()}${element.className && typeof element.className === "string" ? `.${element.className.trim().split(/\s+/).join(".")}` : ""}`;
    const checked = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)).map((element) => ({ selector, element })));
    // the page scroller (`main.app-page`): page overflow shows here, not in the document width
    const scroller = document.querySelector("main");
    const holds = (frame: Element): Element[] => checked.map(({ element }) => element).filter((element) => frame.contains(element));
    const nearestFrame = (element: Element): Element | null => {
      for (let parent = element.parentElement; parent && parent !== root; parent = parent.parentElement) if (clips(parent)) return parent;
      return null;
    };
    // a table's own scroll frame: the table's nearest clipping ancestor, holding that table only
    const tableFrame = (frame: Element): boolean => {
      const regions = holds(frame);
      const table = regions.find((element) => element.tagName === "TABLE" && nearestFrame(element) === frame);
      return table !== undefined && regions.every((element) => table.contains(element));
    };
    return {
      viewport: root.clientWidth,
      scrollWidth: root.scrollWidth,
      elements: checked.map(({ selector, element }) => {
        const box = element.getBoundingClientRect();
        let left = box.left;
        let right = box.right;
        for (let parent = element.parentElement; parent && parent !== root; parent = parent.parentElement) {
          if (!clips(parent)) continue;
          const frame = parent.getBoundingClientRect();
          left = Math.max(left, frame.left);
          right = Math.min(right, frame.right);
        }
        return {
          selector, text: element.textContent?.trim().slice(0, 90), left: box.left, right: box.right,
          shownLeft: left, shownRight: right, width: box.width, height: box.height, display: getComputedStyle(element).display,
        };
      }),
      // frames that scroll or cut the page or a checked region, except a table's own scroll frame
      overflowing: Array.from(document.querySelectorAll("body *"))
        .filter((frame) => clips(frame) && frame.scrollWidth > frame.clientWidth + 2)
        .filter((frame) => (scroller !== null && frame.contains(scroller)) || (holds(frame).length > 0 && !tableFrame(frame)))
        .map((frame) => ({ frame: label(frame), scrollWidth: frame.scrollWidth, clientWidth: frame.clientWidth })),
    };
  }, selectors);
}

/**
 * Record rendered bounds before asserting, so every failed width has reviewable evidence.
 *
 * An element passes when the part of it that shows (its box cut by every ancestor that clips
 * horizontally) lies inside the viewport. A wide table may scroll in its own frame (spec 4.2:
 * "horizontal scroll when wide"): the table's nearest clipping ancestor, holding no other
 * checked region. Any other frame that scrolls or cuts a checked region (a panel, the nav, a
 * sidebar) fails, and so does the page scroller `main` (or a clipping ancestor of it) whenever
 * it overflows sideways, whatever it holds.
 */
export async function checkLayout(page: Page, info: TestInfo, name: string, width: number, selectors: string[]): Promise<void> {
  const geometry = await measureLayout(page, width, selectors);
  await info.attach(`${name}-${width}-bounds`, { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
  if (width === 1280 || width === 2000) {
    await page.screenshot({ path: info.outputPath(`${name}-${width}.png`), fullPage: true });
    await page.screenshot({ path: info.outputPath(`${name}-${width}-viewport.png`) });
  }
  expect.soft(geometry.scrollWidth, `${name} page overflow at ${width}`).toBeLessThanOrEqual(geometry.viewport + 2);
  expect.soft(geometry.overflowing, `${name} frames overflowing at ${width}`).toEqual([]);
  for (const element of geometry.elements.filter((element) => element.display !== "none" && element.width > 0)) {
    expect.soft(element.shownLeft, `${name} ${element.selector} left: ${element.text}`).toBeGreaterThanOrEqual(-2);
    expect.soft(element.shownRight, `${name} ${element.selector} right: ${element.text}`).toBeLessThanOrEqual(geometry.viewport + 2);
  }
}
