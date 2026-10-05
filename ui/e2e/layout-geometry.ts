import type { Page, TestInfo } from "@playwright/test";
import { expect } from "./fixtures";

export const LAYOUT_WIDTHS = [800, 1099, 1101, 1600] as const;

/** Record rendered bounds before asserting, so every failed width has reviewable evidence. */
export async function checkLayout(page: Page, info: TestInfo, name: string, width: number, selectors: string[]): Promise<void> {
  await page.setViewportSize({ width, height: 1000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);
  const geometry = await page.evaluate((selectors) => {
    const root = document.documentElement;
    return {
      viewport: root.clientWidth,
      scrollWidth: root.scrollWidth,
      elements: selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)).map((element) => {
        const box = element.getBoundingClientRect();
        return { selector, text: element.textContent?.trim().slice(0, 90), left: box.left, right: box.right, width: box.width, height: box.height, display: getComputedStyle(element).display };
      })),
    };
  }, selectors);
  await info.attach(`${name}-${width}-bounds`, { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
  if (width === 800 || width === 1600) {
    await page.screenshot({ path: info.outputPath(`${name}-${width}.png`), fullPage: true });
    await page.screenshot({ path: info.outputPath(`${name}-${width}-viewport.png`) });
  }
  expect.soft(geometry.scrollWidth, `${name} page overflow at ${width}`).toBeLessThanOrEqual(geometry.viewport + 2);
  for (const element of geometry.elements.filter((element) => element.display !== "none" && element.width > 0)) {
    expect.soft(element.left, `${name} ${element.selector} left: ${element.text}`).toBeGreaterThanOrEqual(-2);
    expect.soft(element.right, `${name} ${element.selector} right: ${element.text}`).toBeLessThanOrEqual(geometry.viewport + 2);
  }
}
