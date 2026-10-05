import { randomUUID } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { demoTask, expect, getJson, type RunLite, test } from "./fixtures";
import { freePort, REPO_ROOT } from "./paths";

test.use({ unlock: false });

/** Observe only the selected public protocol, never offered ticket protocols. */
async function observeProtocol(page: import("@playwright/test").Page): Promise<void> {
  await page.addInitScript(() => {
    const Native = window.WebSocket;
    window.WebSocket = class extends Native {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        this.addEventListener("open", () => {
          (window as unknown as { selectedProtocol: string }).selectedProtocol = this.protocol;
        });
      }
    };
  });
}

test("Token gate unlocks overview/run, reloads, and receives authenticated live events", async ({ page, request, authToken }, info) => {
  const urls: string[] = []; const frames: string[] = []; const apiAuth: boolean[] = [];
  page.on("request", (req) => {
    urls.push(req.url());
    if (req.url().includes("/api/v1/") && !req.url().endsWith("/projects")) apiAuth.push(req.headers().authorization === `Bearer ${authToken}`);
  });
  page.on("websocket", (socket) => {
    urls.push(socket.url());
    socket.on("framereceived", (frame) => frames.push(String(frame.payload)));
  });
  await observeProtocol(page);
  await page.goto("/");
  await expect(page.getByLabel("Token", { exact: true })).toBeVisible();
  expect(urls.filter((url) => url.includes("/api/v1/")).every((url) => url.endsWith("/projects"))).toBe(true);
  await page.getByLabel("Token", { exact: true }).fill("incorrect-synthetic");
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("Token", { exact: true }).fill(authToken);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByLabel("Token", { exact: true })).toHaveCount(0);
  await expect.poll(() => frames.some((frame) => frame.includes('"type":"ready"'))).toBe(true);
  await page.reload();
  await expect(page.getByLabel("Token", { exact: true })).toHaveCount(0);
  const { project, task } = demoTask("generic");
  const runs = await getJson<RunLite[]>(request, `/api/v1/runs?project=${project}&task=${task}&status=finished&limit=3`);
  const index = info.project.name === "vite-auth" ? 2 : info.project.name === "dark" ? 1 : 0;
  const run = runs[index];
  if (!run) throw new Error("demo lacks auth acceptance run");
  frames.length = 0;
  await page.goto(`/r/${run.run_id}`);
  await expect(page.getByText(run.hypothesis || run.run_id).first()).toBeVisible();
  await expect.poll(() => frames.some((frame) => frame.includes('"type":"ready"'))).toBe(true);
  const text = `auth live ${randomUUID()}`;
  const changed = await request.post(`/api/v1/runs/${run.run_id}/notes`, { data: { text, author: "e2e" } });
  expect(changed.status()).toBe(200);
  await expect(page.getByText(text)).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { selectedProtocol: string }).selectedProtocol)).toBe("hypothex.v1");
  expect(apiAuth.length).toBeGreaterThan(0); expect(apiAuth.every(Boolean)).toBe(true);
  expect(urls.some((url) => url.includes(authToken) || url.includes("ticket="))).toBe(false);
  expect(await page.locator("body").textContent()).not.toContain(authToken);
  // Simulate a rotated token at the protected request boundary: cache and page must disappear.
  const expired = page.waitForResponse((response) => response.url().includes("/api/v1/overview") && response.status() === 401);
  await page.route("**/api/v1/overview**", (route) => route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"unauthorized"}' }));
  await page.goto("/");
  await expect(page.getByLabel("Token", { exact: true })).toBeVisible();
  await expired;
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem("hx-transport-token") === null && sessionStorage.getItem("hx-ws-sequence") === null)).toBe(true);
  await page.unroute("**/api/v1/overview**");
  await page.getByLabel("Token", { exact: true }).fill(authToken);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByLabel("Token", { exact: true })).toHaveCount(0);
});

test("explicit loopback no-auth server opens without a token and negotiates fixed protocol", async ({ browser }) => {
  const home = mkdtempSync(join(tmpdir(), "hx-e2e-noauth-"));
  const port = freePort(); const url = `http://127.0.0.1:${port}`;
  const env: NodeJS.ProcessEnv = { ...process.env, HYPOTHEX_HOME: home, HYPOTHEX_SSH: "false", HYPOTHEX_SCP: "false" };
  delete env.HYPOTHEX_SERVE_TOKEN; delete env.HYPOTHEX_HUB_TOKEN;
  const found = spawnSync("uv", ["run", "--project", REPO_ROOT, "python", "-c", "import os,sys; print(os.path.join(os.path.dirname(sys.executable), 'hx'))"], { encoding: "utf8", env });
  if (found.status !== 0) throw new Error("Cannot locate test hx");
  const server = spawn(found.stdout.trim(), ["--home", home, "serve", "--port", String(port), "--no-auth"], { cwd: REPO_ROOT, env, stdio: "ignore" });
  const context = await browser.newContext(); const page = await context.newPage();
  await observeProtocol(page);
  const ready: string[] = [];
  page.on("websocket", (socket) => { socket.on("framereceived", (frame) => ready.push(String(frame.payload))); });
  try {
    await expect.poll(async () => {
      if (server.exitCode !== null) throw new Error("Noauth server exited");
      try { const res = await fetch(`${url}/api/v1/projects`); return res.status; } catch { return 0; }
    }, { timeout: 20_000 }).toBe(200);
    await page.goto(url);
    await expect(page.getByLabel("Token", { exact: true })).toHaveCount(0);
    await expect.poll(() => ready.some((frame) => frame.includes('"type":"ready"'))).toBe(true);
    expect(await page.evaluate(() => (window as unknown as { selectedProtocol: string }).selectedProtocol)).toBe("hypothex.v1");
    expect(await page.evaluate(() => sessionStorage.getItem("hx-transport-token") === null)).toBe(true);
  } finally {
    await context.close();
    if (server.exitCode === null) {
      const ended = new Promise<void>((resolve) => server.once("exit", () => resolve()));
      server.kill("SIGTERM");
      const timer = setTimeout(() => server.kill("SIGKILL"), 10_000);
      await ended; clearTimeout(timer);
    }
    rmSync(home, { recursive: true, force: true });
  }
});
