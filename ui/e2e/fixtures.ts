/** Shared Playwright fixtures: theme per project, console-error guard, API helpers. */
import { readFileSync } from "node:fs";
import { type APIRequestContext, test as base, expect, type Page } from "@playwright/test";
import { DEMO_FILE, type Kind } from "./paths";

export { expect };

export type Theme = "light" | "dark";
export interface ThemeOptions {
  theme: Theme;
}

/** `--paper` from docs/mockups/ui-v4/index.html: #F6F7F3 (light), #12161C (dark). */
export const PAPER: Record<Theme, string> = {
  light: "rgb(246, 247, 243)",
  dark: "rgb(18, 22, 28)",
};

export interface RunLite {
  run_id: string;
  hypothesis: string;
  status: string;
}
export interface ViewInfoLite {
  name: string;
  title: string;
  origin: "preset" | "inline" | "file";
  path: string | null;
}
export interface PanelLite {
  type: string;
  title: string;
  data?: { source?: string | null } | null;
}
export interface BoardLite {
  headline: string;
  kind: string;
  primary: string;
  rows: { group_id: string; latest_run_id: string }[];
}
export interface ExampleDiffLite {
  fixed: string[];
  broken: string[];
  both_pass: number;
  both_fail: number;
}
export interface ProjectLite {
  project: string;
  repo: string;
}
export interface OverviewLite {
  headline: string;
  projects: { project: string; task: string }[];
}

interface Fixtures {
  consoleErrors: string[];
}

export const test = base.extend<ThemeOptions & Fixtures>({
  theme: ["light", { option: true }],
  page: async ({ page, theme }, use) => {
    await page.addInitScript((value) => {
      window.localStorage.setItem("hx-theme", value);
    }, theme);
    await use(page);
  },
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => {
        errors.push(`pageerror: ${error.message}`);
      });
      await use(errors);
      expect(errors, "browser console errors").toEqual([]);
    },
    { auto: true },
  ],
});

/** The page is in `theme`: attribute set and the paper colour applied. */
export async function expectTheme(page: Page, theme: Theme): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator("body")).toHaveCSS("background-color", PAPER[theme]);
}

/** Project and task that `hx demo` seeded for `kind` (read after the server started). */
export function demoTask(kind: Kind): { project: string; task: string } {
  const seeded = JSON.parse(readFileSync(DEMO_FILE, "utf8")) as Record<string, string>;
  const ref = seeded[kind];
  if (!ref || !ref.includes("/")) throw new Error(`hx demo did not seed kind ${kind}`);
  const slash = ref.indexOf("/");
  return { project: ref.slice(0, slash), task: ref.slice(slash + 1) };
}

export async function getJson<T>(request: APIRequestContext, url: string): Promise<T> {
  const response = await request.get(url);
  expect(response.status(), `GET ${url}`).toBe(200);
  return (await response.json()) as T;
}

export async function postJson<T>(
  request: APIRequestContext,
  url: string,
  body: unknown,
): Promise<T> {
  const response = await request.post(url, { data: body });
  expect(response.status(), `POST ${url}`).toBe(200);
  return (await response.json()) as T;
}
