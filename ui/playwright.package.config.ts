import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./package-e2e",
  outputDir: process.env.HX_PACKAGE_BROWSER_OUTPUT,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"]],
  timeout: 110000,
  expect: { timeout: 10000 },
  use: { actionTimeout: 10000, trace: "off", screenshot: "off", video: "off" },
  projects: ["light", "dark"].map((theme) => ({
    name: theme,
    use: {
      ...devices["Desktop Chrome"],
      viewport: { width: 1440, height: 1000 },
      colorScheme: theme as "light" | "dark",
    },
  })),
});
