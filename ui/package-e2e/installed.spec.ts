import { execFileSync } from "node:child_process";
import { readFileSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";
import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import type { TaskRuns, NotebookDay } from "../src/api/models";

type Descriptor = {
  url: string;
  environment_id: string;
  scenario: string;
  stage: string;
  root: string;
  home: string;
  interpreter: string;
  cli: string;
  demo: Record<string, unknown>;
  environment: Record<string, string>;
};
function inside(path: string, root: string): boolean {
  const rel = relative(realpathSync(root), realpathSync(path));
  return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
}
function local(url: string): boolean {
  const u = new URL(url);
  return (
    ["http:", "https:", "ws:", "wss:"].includes(u.protocol) &&
    ["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)
  );
}

test("installed pages and authenticated reloads", async ({
  browser,
}, testInfo) => {
  const descriptorPath = process.env.HX_PACKAGE_DESCRIPTOR;
  if (!descriptorPath) throw new Error("Package descriptor is required");
  expect(statSync(descriptorPath).mode & 0o777).toBe(0o600);
  const d = JSON.parse(readFileSync(descriptorPath, "utf8")) as Descriptor;
  expect(local(d.url)).toBe(true);
  expect(inside(descriptorPath, d.root)).toBe(true);
  for (const path of [d.home, d.cli]) expect(inside(path, d.root)).toBe(true);
  expect(inside(resolve(d.interpreter, ".."), d.root)).toBe(true);
  expect(Object.keys(d.environment).some((key) => key.startsWith("PG"))).toBe(
    false,
  );
  const server = JSON.parse(
    readFileSync(resolve(d.home, "serve/server.json"), "utf8"),
  );
  expect(realpathSync(server.home)).toBe(realpathSync(d.home));
  expect(server.environment_id).toBe(d.environment_id);
  process.kill(server.pid, 0);
  const token = execFileSync(d.cli, ["--home", d.home, "token"], {
    cwd: resolve(d.root, "cwd"),
    env: d.environment,
    encoding: "utf8",
    timeout: 30000,
  }).trim();
  if (!token) throw new Error("Installed CLI returned no owner credential");
  const failures: string[] = [];
  const errors: string[] = [];
  async function context(): Promise<BrowserContext> {
    const c = await browser.newContext({
      baseURL: d.url,
      colorScheme: testInfo.project.name as "light" | "dark",
    });
    await c.addInitScript((theme) => {
      if (location.protocol === "http:" || location.protocol === "https:")
        localStorage.setItem("hx-theme", theme);
    }, testInfo.project.name);
    await c.route("**/*", async (route) => {
      if (local(route.request().url())) await route.continue();
      else {
        failures.push("non-loopback request");
        await route.abort();
      }
    });
    await c.routeWebSocket("**/*", (ws) => {
      if (local(ws.url())) ws.connectToServer();
      else {
        failures.push("non-loopback websocket");
        ws.close();
      }
    });
    c.on("page", (p) => {
      p.on("pageerror", (error) =>
        errors.push(error.message.split(token).join("[redacted]")),
      );
      p.on("response", (r) => {
        const u = new URL(r.url());
        if (
          (u.pathname.startsWith("/assets/") ||
            /\.(js|css)$/.test(u.pathname)) &&
          r.status() >= 400
        )
          failures.push(`static ${r.status()}`);
      });
    });
    return c;
  }
  const admin = await context();
  const page = await admin.newPage();
  const ownerHeaders = { Authorization: `Bearer ${token}` };
  async function json<T>(path: string): Promise<T> {
    const response = await admin.request.get(d.url + path, {
      headers: ownerHeaders,
    });
    expect(response.ok()).toBe(true);
    return (await response.json()) as T;
  }
  async function pair(
    c: BrowserContext,
    p: Page,
    user: string,
    scope: string,
  ): Promise<void> {
    const offered = await admin.request.post(d.url + "/api/v1/auth/pairings", {
      headers: ownerHeaders,
      data: { user, scope, ttl_seconds: 300 },
    });
    expect(offered.ok()).toBe(true);
    const hash = new URL((await offered.json()).url).hash;
    await c.addInitScript((fragment) => {
      if (
        location.pathname === "/pair" &&
        !sessionStorage.getItem("package-pair-used")
      ) {
        history.replaceState(null, "", "/pair" + fragment);
        sessionStorage.setItem("package-pair-used", "1");
      }
    }, hash);
    await p.goto(d.url + "/pair");
    await p
      .getByLabel("Device name", { exact: true })
      .fill("Installed package browser");
    await p.getByRole("button", { name: "Pair", exact: true }).click();
    await expect(
      p.getByRole("heading", { name: "Device paired", exact: true }),
    ).toBeVisible();
    expect(await p.evaluate(() => location.hash === "")).toBe(true);
    const me = await c.request.get(d.url + "/api/v1/auth/me");
    expect(me.ok()).toBe(true);
    const body = await me.json();
    expect(body.user).toBe(user);
    expect(body.scope).toBe(scope);
  }
  async function reload(path: string, heading: string): Promise<void> {
    await page.goto(d.url + path);
    await expect(
      page.getByRole("heading", { name: heading, exact: true, level: 1 }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("heading", { name: heading, exact: true, level: 1 }),
    ).toBeVisible();
  }
  try {
    if (d.scenario === "token") {
      await page.goto(d.url + "/hosts");
      await page.getByLabel("Token", { exact: true }).fill(token);
      await page.getByRole("button", { name: "Unlock", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "Hosts", level: 1 }),
      ).toBeVisible();
    } else {
      const me = await json<{ user: string }>("/api/v1/auth/me");
      await pair(admin, page, me.user, "admin");
    }
    await page.goto(d.url + "/");
    await expect(
      page.getByRole("navigation", { name: "Navigation", exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("navigation", { name: "Navigation", exact: true }),
    ).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute(
      "data-theme",
      testInfo.project.name,
    );
    for (const heading of [/^Tasks/, /^Recent runs/])
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    const mapping =
      typeof d.demo.generic === "string" ? d.demo.generic : "toy/toy-acc";
    const [project, task] = mapping.split("/");
    const path = `/t/${encodeURIComponent(project)}/${encodeURIComponent(task)}`;
    await expect(page.locator(`a[href="${path}"]`).first()).toBeVisible();
    for (const heading of ["Hosts", "Queue", "Settings", "Storage"])
      await reload("/" + heading.toLowerCase(), heading);
    await reload(path, task);
    await expect(
      page.getByRole("tablist", { name: "Task", exact: true }),
    ).toBeVisible();
    for (const name of [
      "Charts",
      /^Runs(?:\s*\d+)?$/,
      /^Sweeps(?:\s*\d+)?$/,
      "Examples",
    ])
      await expect(page.getByRole("tab", { name, exact: true })).toBeVisible();
    const sidebar = page.getByRole("complementary", {
      name: "Runs",
      exact: true,
    });
    await expect(sidebar).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Scores", exact: true }),
    ).toBeVisible();
    await sidebar
      .getByLabel("Filter runs", { exact: true })
      .fill("status:finished");
    await sidebar
      .getByRole("button", { name: "Each run", exact: true })
      .click();
    await sidebar.getByRole("button", { name: /^Sort/ }).click();
    await page.getByRole("menuitemradio", { name: /created/i }).click();
    await sidebar
      .getByRole("button", { name: /^Hide / })
      .first()
      .click();
    const selectedUrl = page.url();
    await page.reload();
    expect(page.url()).toBe(selectedUrl);
    await expect(
      sidebar.getByLabel("Filter runs", { exact: true }),
    ).toHaveValue("status:finished");
    await page.goto(d.url + path);
    await page.getByRole("tab", { name: /^Runs(?:\s*\d+)?$/ }).click();
    await expect(
      page.getByRole("table", { name: "Runs", exact: true }),
    ).toBeVisible();
    const rows = await json<TaskRuns>(`/api/v1/tasks/${project}/${task}/runs`);
    await json(`/api/v1/tasks/${project}/${task}/leaderboard`);
    const row = rows.runs.find((r) =>
      d.scenario.startsWith("schema")
        ? r.run_id === "a"
        : Object.keys(r.scores).length > 0,
    );
    if (!row) throw new Error("No scored installed run");
    const display = row.renamed
      ? row.name
      : `${row.derived_name}${row.seed == null ? "" : ` · seed ${row.seed}`}`;
    await page.goto(d.url + `/r/${row.run_id}`);
    await expect(page.locator("h1")).toContainText(display!);
    await page.reload();
    await expect(page.locator("h1")).toContainText(display!);
    await expect(
      page.getByRole("tablist", { name: "Run", exact: true }),
    ).toBeVisible();
    const properties = page.getByRole("complementary", {
      name: "Properties",
      exact: true,
    });
    await expect(properties).toBeVisible();
    for (const label of ["Status", "Launcher", "Host", "Started", "Commit"])
      await expect(properties.getByText(label, { exact: true })).toBeVisible();
    await expect(
      page.getByText("Where it ranks", { exact: true }),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Files", exact: true }).click();
    const notebookPath = d.scenario.startsWith("schema")
      ? "/n/toy/2026-10-06"
      : `/n/${project}`;
    await page.goto(d.url + notebookPath);
    const day = d.scenario.startsWith("schema")
      ? "2026-10-06"
      : (await json<NotebookDay>(`/api/v1/projects/${project}/notebook/today`))
          .day;
    await expect(
      page.getByRole("heading", { name: day, level: 2, exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("heading", { name: day, level: 2, exact: true }),
    ).toBeVisible();
    if (d.scenario.startsWith("schema"))
      await expect(
        page.getByText("package upgrade", { exact: false }),
      ).toBeVisible();
    if (d.scenario === "team") {
      await page.goto(d.url + path);
      await expect(
        page.getByRole("table", { name: "Paper baselines", exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Export", exact: true });
      await expect(page.getByRole("dialog")).toHaveCount(1);
      await expect(dialog).toBeVisible();
      for (const format of ["latex", "markdown", "csv"]) {
        await dialog
          .getByRole("combobox", { name: "Format", exact: true })
          .selectOption(format);
        await expect(
          dialog.getByRole("button", { name: "Download", exact: true }),
        ).toBeEnabled();
      }
      await page.keyboard.press("Escape");
    }
    if (typeof d.demo.eval_matrix === "string") {
      const [ep, et] = d.demo.eval_matrix.split("/");
      await page.goto(d.url + `/t/${ep}/${et}`);
      await page
        .getByRole("button", { name: "Table", exact: true })
        .first()
        .click();
      await expect(
        page.getByRole("table", { name: "Compare table", exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Bars", exact: true })
        .first()
        .click();
      await expect(
        page.getByRole("table", { name: "Compare table", exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Bars", exact: true }).first(),
      ).toHaveAttribute("aria-pressed", "true");
    }
    if (Object.keys(d.demo).length > 0) {
      let selected = false;
      for (const mapping of Object.values(d.demo)) {
        if (typeof mapping !== "string" || !mapping.includes("/")) continue;
        const [sp] = mapping.split("/");
        const sweeps = await json<Array<{ id: string; n_runs: number }>>(
          `/api/v1/projects/${sp}/sweeps`,
        );
        const sweep = sweeps.find((value) => value.n_runs > 0);
        if (!sweep) continue;
        const detail = await json<{ spec: { task: string | null } }>(
          `/api/v1/sweeps/${sp}/${sweep.id}`,
        );
        expect(typeof detail.spec.task).toBe("string");
        await page.goto(d.url + `/s/${sp}/${sweep.id}`);
        // The accessible name includes the count once task data has loaded.
        await expect(
          page.getByRole("tab", { name: /^Sweeps(?:\s*\d+)?$/ }),
        ).toHaveAttribute("aria-selected", "true");
        expect(new URL(page.url()).pathname).toBe(
          `/t/${sp}/${detail.spec.task}`,
        );
        expect(new URL(page.url()).searchParams.get("sweep")).toBe(sweep.id);
        await expect(
          page
            .getByRole("navigation", { name: "Sweeps", exact: true })
            .getByRole("button", { name: new RegExp(sweep.id) }),
        ).toHaveAttribute("aria-current", "true");
        selected = true;
        break;
      }
      expect(selected).toBe(true);
    }
    if (d.scenario !== "token") {
      const scoped = await context();
      try {
        const p = await scoped.newPage();
        await pair(scoped, p, "alice", "launch");
        const paths: string[] = [];
        p.on("request", (r) => paths.push(new URL(r.url()).pathname));
        await p.goto(d.url + "/settings");
        await expect(
          p.getByRole("region", { name: "Sessions", exact: true }),
        ).toBeVisible();
        await expect(
          p.getByRole("region", { name: "Users", exact: true }),
        ).toHaveCount(0);
        await expect(
          p.getByRole("region", { name: "Notifications", exact: true }),
        ).toHaveCount(0);
        await p.goto(d.url + "/storage");
        await expect(
          p.getByText("Storage requires admin scope."),
        ).toBeVisible();
        expect(
          paths.some((v) =>
            [
              "/api/v1/auth/users",
              "/api/v1/notify",
              "/api/v1/storage",
            ].includes(v),
          ),
        ).toBe(false);
        await p.goto(d.url + `/r/${row.run_id}`);
        if (row.owner)
          await expect(
            p.getByRole("complementary", { name: "Properties" }),
          ).toContainText("@" + row.owner);
        else
          await expect(
            p
              .getByRole("complementary", { name: "Properties" })
              .getByText("Owner", { exact: true }),
          ).toHaveCount(0);
        if (d.scenario === "team")
          for (const [runId, owner] of [
            ["st-a", "sv"],
            ["st-b", "alice"],
          ]) {
            await p.goto(d.url + `/r/${runId}`);
            await expect(
              p
                .getByRole("complementary", { name: "Properties" })
                .getByText("Owner", { exact: true }),
            ).toBeVisible();
            await expect(
              p.getByRole("complementary", { name: "Properties" }),
            ).toContainText("@" + owner);
          }
      } finally {
        await scoped.close();
      }
    }
    expect(errors).toEqual([]);
    expect(failures).toEqual([]);
  } finally {
    await admin.close();
  }
});
