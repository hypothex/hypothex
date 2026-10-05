import { defineConfig, devices } from "@playwright/test";
import type { ThemeOptions } from "./e2e/fixtures";
// Loading paths.ts picks this run's two free ports and puts them in process.env, which the
// workers and both web servers inherit (never a fixed port, ruling S1).
import { HOSTS_PORT, IDENTITY_ROUTE, PORT, VITE_PORT } from "./e2e/paths";

const WRITES = /(editor|live)\.spec\.ts$/;
/** Specs against the `hx demo --with-hosts` hub; `launch` starts runs, so it runs last. */
const HOSTS_READS = /hosts\.spec\.ts$/;
const HOSTS_WRITES = /launch\.spec\.ts$/;
const HOSTS_URL = `http://127.0.0.1:${HOSTS_PORT}`;
/**
 * SIGTERM, then SIGKILL after 90 s: `serve-demo.ts` forwards the SIGTERM to `hx serve`,
 * whose lifespan shutdown stops the demo runs and fake hosts (its own wait is 60 s).
 * Without this Playwright SIGKILLs the group at once.
 */
const GRACEFUL = { signal: "SIGTERM", timeout: 90_000 } as const;

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
    trace: "off",
    screenshot: "off",
  },
  projects: [
    {
      name: "vite-auth",
      testMatch: /auth\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${VITE_PORT}`, colorScheme: "light", theme: "light" },
    },
    {
      name: "light",
      testIgnore: [WRITES, HOSTS_READS, HOSTS_WRITES],
      use: { ...devices["Desktop Chrome"], colorScheme: "light", theme: "light" },
    },
    {
      name: "dark",
      testIgnore: [WRITES, HOSTS_READS, HOSTS_WRITES],
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
    {
      name: "hosts-light",
      testMatch: HOSTS_READS,
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "light", theme: "light" },
    },
    {
      name: "hosts-dark",
      testMatch: HOSTS_READS,
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "dark", theme: "dark" },
    },
    {
      // Launches add queued runs to a fake host, so they wait for the read-only specs.
      name: "hosts-light-edit",
      testMatch: HOSTS_WRITES,
      dependencies: ["hosts-light", "hosts-dark"],
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "light", theme: "light" },
    },
    {
      name: "hosts-dark-edit",
      testMatch: HOSTS_WRITES,
      dependencies: ["hosts-light", "hosts-dark", "hosts-light-edit"],
      use: { ...devices["Desktop Chrome"], baseURL: HOSTS_URL, colorScheme: "dark", theme: "dark" },
    },
  ],
  // Both ports are random per run. Never reuse a server that answers on one anyway: an
  // `hx serve` there may run on the real ~/.hypothex, and live.spec.ts posts notes
  // (forwarded to real hosts in phase 2) and launch.spec.ts starts runs. Playwright fails at
  // start instead, a web server whose command exits stops the run at once, and every test
  // checks the hub's identity first (`isolatedHub` in e2e/fixtures.ts).
  webServer: [
    {
      command: `bun run dev --host 127.0.0.1 --port ${VITE_PORT}`,
      env: { HX_API: `http://127.0.0.1:${PORT}` },
      url: `http://127.0.0.1:${VITE_PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "bun e2e/serve-demo.ts",
      url: `http://127.0.0.1:${PORT}${IDENTITY_ROUTE}`,
      reuseExistingServer: false,
      gracefulShutdown: GRACEFUL,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "bun e2e/serve-demo.ts --with-hosts",
      url: `${HOSTS_URL}${IDENTITY_ROUTE}`,
      reuseExistingServer: false,
      gracefulShutdown: GRACEFUL,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
