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
