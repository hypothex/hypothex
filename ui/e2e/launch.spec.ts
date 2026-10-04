import { expect, expectTheme, getJson, test } from "./fixtures";
import { connectedHosts, type RecordLite, remoteHosts, type TaskLite } from "./hosts-fixtures";

test("the launch dialog starts a run on a fake host", async ({ page, request, theme }) => {
  const hosts = remoteHosts(await connectedHosts(request));
  const host = hosts.find((h) => h.kind === "ssh" && h.projects.length > 0);
  const project = host?.projects[0];
  if (!host || !project) throw new Error("hx demo --with-hosts has no ssh host with a mapped project");
  const tasks = await getJson<TaskLite[]>(request, `/api/v1/tasks?project=${encodeURIComponent(project)}`);
  const task = tasks[0]?.name;
  if (!task) throw new Error(`demo project ${project} has no task`);
  const hypothesis = `e2e launch ${theme} ${Date.now()}`;

  await page.goto(`/t/${encodeURIComponent(project)}/${encodeURIComponent(task)}`);
  await expectTheme(page, theme);
  await page.getByRole("button", { name: "New run" }).click();
  const dialog = page.getByRole("dialog", { name: /New run/ });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio", { name: new RegExp(`^${host.name}\\b`) }).check();
  await dialog.getByLabel(/wait for GPUs/).setChecked(true);
  await dialog.getByLabel("Seeds").fill("7");
  await dialog.getByLabel("Command").fill("echo hx-e2e {seed}");
  await dialog.getByLabel("Hypothesis").fill(hypothesis);
  await dialog.getByRole("button", { name: /^Launch/ }).click();

  // The hub forwards the launch to the host and mirrors the run back. (A holder object,
  // because TypeScript does not see assignments made inside the poll callback.)
  const found: { run?: RecordLite } = {};
  await expect
    .poll(
      async () => {
        const runs = await getJson<RecordLite[]>(
          request,
          `/api/v1/runs?project=${encodeURIComponent(project)}&limit=500`,
        );
        found.run = runs.find((r) => r.hypothesis === hypothesis);
        return found.run?.run_id ?? null;
      },
      { timeout: 30_000, message: "the launched run never reached the hub" },
    )
    .not.toBeNull();
  const made = found.run;
  if (!made) throw new Error("the launched run is missing after the poll");
  const detail = await getJson<{ record: RecordLite }>(request, `/api/v1/runs/${made.run_id}`);
  // the run belongs to the host's environment (executor.host is the machine's hostname)
  expect(detail.record.environment_id).toBe(host.state.environment_id);

  await page.goto(`/r/${made.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(hypothesis);
  await expect(page.getByRole("region", { name: /Placement$/ })).toContainText(host.name);

  // leave the fake host's queue as it was
  const stopped = await request.post(`/api/v1/runs/${made.run_id}/stop`, { data: {} });
  expect(stopped.status()).toBe(200);
});
