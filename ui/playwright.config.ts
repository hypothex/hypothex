import { defineConfig, devices } from "@playwright/test";
import type { ThemeOptions } from "./e2e/fixtures";
import { PORT } from "./e2e/paths";

const WRITES = /(editor|live)\.spec\.ts$/;

export default defineConfig<ThemeOptions>({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "./e2e/.report", open: "never" }]]
    : [["list"]],
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "light",
      testIgnore: WRITES,
      use: { ...devices["Desktop Chrome"], colorScheme: "light", theme: "light" },
    },
    {
      name: "dark",
      testIgnore: WRITES,
      use: { ...devices["Desktop Chrome"], colorScheme: "dark", theme: "dark" },
    },
    {
      name: "light-edit",
      testMatch: WRITES,
      dependencies: ["light", "dark"],
      use: { ...devices["Desktop Chrome"], colorScheme: "light", theme: "light" },
    },
    {
      // Runs after light-edit (not just light/dark): live.spec.ts posts a note to the
      // same shared demo run from both edit projects, and the Notes panel shows only the
      // newest one, so the two projects must not write to it at the same time.
      name: "dark-edit",
      testMatch: WRITES,
      dependencies: ["light", "dark", "light-edit"],
      use: { ...devices["Desktop Chrome"], colorScheme: "dark", theme: "dark" },
    },
  ],
  webServer: {
    command: "bun e2e/serve-demo.ts",
    url: `http://127.0.0.1:${PORT}/.well-known/hypothex/environment`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
