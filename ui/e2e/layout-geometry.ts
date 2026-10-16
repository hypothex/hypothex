import type { Page, TestInfo } from "@playwright/test";
import { expect } from "./fixtures";

/** v5 layout widths (spec section 9); screenshots at the narrowest and the widest. */
export const LAYOUT_WIDTHS = [1280, 1440, 2000] as const;
/** Regions of a v5 screen whose shown part must stay inside the viewport. */
export const LAYOUT_REGIONS = ["[data-panel]", "table", "nav", "aside"];

/**
 * Record rendered bounds before asserting, so every failed width has reviewable evidence.
 *
 * An element passes when the part of it that shows (its box cut by every ancestor that clips
 * horizontally) lies inside the viewport. A wide table may scroll in its own frame (spec 4.2:
 * "horizontal scroll when wide"), but a frame that scrolls or cuts any other checked element
 * (a panel, the nav, a sidebar, the page) is page overflow and fails.
 */
export async function checkLayout(page: Page, info: TestInfo, name: string, width: number, selectors: string[]): Promise<void> {
  await page.setViewportSize({ width, height: 1000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);
  const geometry = await page.evaluate((selectors) => {
    const root = document.documentElement;
    const clips = (element: Element): boolean => getComputedStyle(element).overflowX !== "visible";
    const label = (element: Element): string => `${element.tagName.toLowerCase()}${element.className && typeof element.className === "string" ? `.${element.className.trim().split(/\s+/).join(".")}` : ""}`;
    const checked = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)).map((element) => ({ selector, element })));
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
      // frames that scroll or cut a checked element other than a table
      overflowing: Array.from(document.querySelectorAll("body *"))
        .filter((frame) => clips(frame) && frame.scrollWidth > frame.clientWidth + 2)
        .filter((frame) => checked.some(({ element }) => element.tagName !== "TABLE" && (frame === element || frame.contains(element))))
        .map((frame) => ({ frame: label(frame), scrollWidth: frame.scrollWidth, clientWidth: frame.clientWidth })),
    };
  }, selectors);
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
