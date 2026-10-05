import { checkLayout, LAYOUT_WIDTHS } from "./layout-geometry";
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

test("the Overview Hosts panel lists every fake host", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  expect(hosts.some((h) => h.kind === "slurm")).toBe(true);
  expect(hosts.some((h) => h.kind === "ssh" && h.gpus.length > 0)).toBe(true);

  await page.goto("/");
  await expectTheme(page, theme);
  const panel = page.getByRole("region", { name: "a Hosts" });
  await expect(panel).toBeVisible();
  for (const host of hosts) {
    await expect(panel.getByText(host.name, { exact: true }).first()).toBeVisible();
  }
});

test("the sweep page renders the demo sweep", async ({ page, request, theme }) => {
  await connectedHosts(request);
  const { project, id } = await firstSweep(request);
  const path = `${encodeURIComponent(project)}/${encodeURIComponent(id)}`;
  const summary = await getJson<SweepLite>(request, `/api/v1/sweeps/${path}`);
  expect(summary.spec.id).toBe(id);
  expect(summary.run_ids.length).toBeGreaterThan(0);

  await page.goto(`/s/${path}`);
  await expectTheme(page, theme);
  await expect(page.getByText(summary.headline).first()).toBeVisible();
  for (const name of ["Copy as CLI", "Cancel queued", "Add seeds"]) {
    await expect(page.getByRole("button", { name })).toBeVisible();
  }
});

test("a queued remote run shows its place in the host queue", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  // wait for the demo's running cells to start; the last in the queue (FIFO, posted last)
  // is a cell that stays queued, never one about to start (no 2 GPUs are left free)
  await runningRemoteRun(request, hosts);
  const queued = await getJson<RecordLite[]>(request, "/api/v1/runs?status=queued&limit=500");
  const run = queued
    .filter((r) => r.executor.queue_position && hostOfRun(hosts, r))
    .sort((a, b) => (b.executor.queue_position ?? 0) - (a.executor.queue_position ?? 0))[0];
  const host = run ? hostOfRun(hosts, run)?.name : undefined;
  if (!run || !host) throw new Error("hx demo --with-hosts has no queued run on an ssh host");

  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    new RegExp(`queued \\d+(st|nd|rd|th) on ${host}$`),
  );
  const queue = page.getByRole("region", { name: "a Queue" });
  await expect(queue).toBeVisible();
  await expect(queue.locator('tr[aria-current="true"]')).toContainText(run.run_id.split("-").pop() ?? "");
  await expect(page.getByRole("region", { name: /Placement$/ })).toContainText(host);
});

test("a running remote run shows its host and CUDA_VISIBLE_DEVICES", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const { run, host: row } = await runningRemoteRun(request, hosts);
  const host = row.name;

  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  const placement = page.getByRole("region", { name: /Placement$/ });
  await expect(placement).toContainText(host);
  await expect(placement).toContainText(`CUDA_VISIBLE_DEVICES=${(run.executor.gpus ?? []).join(",")}`);
  await expect(page.locator(".status")).toContainText(host);
});

test("step7 host, sweep, and queue switch geometry at breakpoint widths", async ({ page, request, theme }, info) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const { run, host } = await runningRemoteRun(request, hosts);
  await page.goto("/");
  await expectTheme(page, theme);
  await expect(page.locator(".hosts .hrow").last()).toBeVisible();
  for (const width of LAYOUT_WIDTHS) {
    await checkLayout(page, info, "hosts", width, [".hosts .hrow", ".hosts .gc", ".hosts .hn", ".hosts .slurm"]);
  }
  const { project, id } = await firstSweep(request);
  await page.goto(`/s/${encodeURIComponent(project)}/${encodeURIComponent(id)}`);
  await expect(page.locator(".sw-grid")).toBeVisible();
  for (const width of LAYOUT_WIDTHS) {
    await checkLayout(page, info, "sweep", width, [".run-top h1", ".run-top .actions", ".run-top button", ".sw-grid"]);
  }
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
