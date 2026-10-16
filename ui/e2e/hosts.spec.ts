import type { APIRequestContext } from "@playwright/test";
import { checkLayout, LAYOUT_REGIONS, LAYOUT_WIDTHS } from "./layout-geometry";
import { expect, expectTheme, getJson, test } from "./fixtures";
import {
  connectedHosts,
  firstSweep,
  hostOfRun,
  type RecordLite,
  remoteHosts,
  runningRemoteRun,
  type SweepLite,
} from "./hosts-fixtures";

/** The last run in an ssh host's queue (FIFO, posted last): one that stays queued. */
async function lastQueuedRun(request: APIRequestContext): Promise<{ run: RecordLite; host: string }> {
  const hosts = remoteHosts(await connectedHosts(request));
  // wait for the demo's running cells to start; no 2 GPUs are left free after that
  await runningRemoteRun(request, hosts);
  const queued = await getJson<RecordLite[]>(request, "/api/v1/runs?status=queued&limit=500");
  const run = queued
    .filter((r) => r.executor.queue_position && hostOfRun(hosts, r))
    .sort((a, b) => (b.executor.queue_position ?? 0) - (a.executor.queue_position ?? 0))[0];
  const host = run ? hostOfRun(hosts, run)?.name : undefined;
  if (!run || !host) throw new Error("hx demo --with-hosts has no queued run on an ssh host");
  return { run, host };
}

test("hosts page shows every configured host with GPU cells", async ({ page, request, theme }) => {
  const hosts = await connectedHosts(request);
  const remote = remoteHosts(hosts);
  expect(remote.some((h) => h.kind === "slurm")).toBe(true);
  expect(remote.some((h) => h.kind === "ssh" && h.gpus.length > 0)).toBe(true);

  await page.goto("/hosts");
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1, name: "Hosts" })).toBeVisible();
  for (const host of hosts) {
    const row = page.getByRole("row", { name: host.name, exact: true });
    await expect(row).toBeVisible();
    await expect(row.locator("[data-gpu]")).toHaveCount(host.gpus.length);
  }
});

// spec section 9 on the hosts hub: Hosts and Queue without overflow at every layout width
for (const screen of ["Hosts", "Queue"]) {
  test(`${screen.toLowerCase()} page: no overflow at ${LAYOUT_WIDTHS.join("/")}`, async ({ page, request, theme }, info) => {
    await connectedHosts(request);
    await page.goto(`/${screen.toLowerCase()}`);
    await expectTheme(page, theme);
    await expect(page.getByRole("heading", { level: 1, name: screen })).toBeVisible();
    await expect(page.getByRole("table").first()).toBeVisible();
    for (const width of LAYOUT_WIDTHS) {
      await checkLayout(page, info, screen.toLowerCase(), width, LAYOUT_REGIONS);
    }
  });
}

test("queue page lists queued runs with their position", async ({ page, request, theme }) => {
  const { run } = await lastQueuedRun(request);
  await page.goto("/queue");
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1, name: "Queue" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: /queued/i }).first()).toBeVisible();
  const row = page.getByRole("row").filter({ has: page.locator(`a[href="/r/${run.run_id}"]`) });
  await expect(row.locator("td").first()).toHaveText(String(run.executor.queue_position));
});

test("a sweep link opens the demo sweep in its task's Sweeps tab", async ({ page, request, theme }) => {
  await connectedHosts(request);
  const { project, id } = await firstSweep(request);
  const path = `${encodeURIComponent(project)}/${encodeURIComponent(id)}`;
  const summary = await getJson<SweepLite>(request, `/api/v1/sweeps/${path}`);
  expect(summary.spec.id).toBe(id);
  expect(summary.run_ids.length).toBeGreaterThan(0);

  await page.goto(`/s/${path}`);
  await expectTheme(page, theme);
  if (summary.spec.task !== null) {
    const task = `/t/${encodeURIComponent(project)}/${encodeURIComponent(summary.spec.task)}`;
    await expect(page).toHaveURL((url) => url.pathname === task && url.searchParams.get("tab") === "sweeps" && url.searchParams.get("sweep") === id);
  }
  await expect(page.getByRole("heading", { level: 2, name: id })).toBeVisible();
  for (const name of ["Copy as CLI", "Cancel queued", "Add seeds"]) {
    await expect(page.getByRole("button", { name })).toBeVisible();
  }
});

test("a queued remote run shows its place in the host queue", async ({ page, request, theme }) => {
  const { run, host } = await lastQueuedRun(request);
  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("status").filter({ hasText: /^Queued / }).locator("b")).toHaveText(
    new RegExp(`^Queued \\d+(st|nd|rd|th)( of \\d+)? on ${host}$`),
  );
  const queue = page.getByRole("region", { name: "Queue", exact: true });
  await expect(queue).toBeVisible();
  await expect(queue.locator('tr[aria-current="true"]')).toContainText(run.run_id.split("-").pop() ?? "");
  const props = page.getByRole("complementary", { name: "Properties" });
  await expect(props).toContainText(host);
  await expect(props.getByText("Queue", { exact: true })).toBeVisible();
});

test("a running remote run shows its host and CUDA_VISIBLE_DEVICES", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const { run, host } = await runningRemoteRun(request, hosts);

  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  const props = page.getByRole("complementary", { name: "Properties" });
  await expect(props).toContainText(host.name);
  await expect(props).toContainText(`CUDA_VISIBLE_DEVICES=${(run.executor.gpus ?? []).join(",")}`);
});

test("the launch dialog's queue switch keeps its label on one line", async ({ page, request }, info) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const { run, host } = await runningRemoteRun(request, hosts);
  const tasks = await getJson<{ name: string }[]>(request, `/api/v1/tasks?project=${encodeURIComponent(run.project)}`);
  const task = tasks[0]?.name;
  if (!task) throw new Error("fake-host project lacks a task");
  await page.goto(`/t/${encodeURIComponent(run.project)}/${encodeURIComponent(task)}`);
  await page.getByRole("button", { name: "New run" }).click();
  await page.getByRole("radio", { name: host.name, exact: true }).check();
  for (const width of LAYOUT_WIDTHS) {
    await checkLayout(page, info, "queue-switch", width, [".hx-launch .dlg", ".hx-launch .hx-sw"]);
    const shape = await page.locator(".hx-sw").evaluate((element) => {
      const text = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.includes("wait for GPUs"));
      if (!text) throw new Error("queue label text missing");
      const range = document.createRange();
      const start = text.textContent!.indexOf("wait for GPUs");
      range.setStart(text, start);
      range.setEnd(text, start + "wait for GPUs".length);
      return { lines: range.getClientRects().length, labelWidth: element.getBoundingClientRect().width, textWidth: range.getBoundingClientRect().width };
    });
    expect.soft(shape.lines).toBe(1);
    expect.soft(shape.labelWidth).toBeGreaterThan(shape.textWidth + 30);
  }
});
