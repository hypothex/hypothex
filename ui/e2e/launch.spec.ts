import type { APIRequestContext, Page } from "@playwright/test";
import { expect, expectTheme, getJson, test, type Theme } from "./fixtures";
import { connectedHosts, type HostLite, type RecordLite, remoteHosts, type TaskLite } from "./hosts-fixtures";

interface Target {
  host: HostLite;
  project: string;
  task: string;
}

/** The demo's ssh host with a mapped project, and a task of that project. */
async function sshTarget(request: APIRequestContext): Promise<Target> {
  const hosts = remoteHosts(await connectedHosts(request));
  const host = hosts.find((h) => h.kind === "ssh" && h.projects.length > 0);
  const project = host?.projects[0];
  if (!host || !project) throw new Error("hx demo --with-hosts has no ssh host with a mapped project");
  const tasks = await getJson<TaskLite[]>(request, `/api/v1/tasks?project=${encodeURIComponent(project)}`);
  const task = tasks[0]?.name;
  if (!task) throw new Error(`demo project ${project} has no task`);
  return { host, project, task };
}

/**
 * Fill the New run dialog for seed 7 of `echo hx-e2e {seed}` on the target host, launch it,
 * and return the run once the hub mirrors it. `gpus` 0 runs at once (the demo's running
 * runs hold every GPU of the host); `queue` makes it wait for GPUs.
 */
async function launch(
  page: Page,
  request: APIRequestContext,
  theme: Theme,
  { host, project, task }: Target,
  { gpus, queue }: { gpus: number; queue: boolean },
): Promise<RecordLite> {
  // short: a long hypothesis is cut in the run page's title
  const hypothesis = `e2e ${queue ? "queue" : "run"} ${theme} ${Date.now()}`;
  await page.goto(`/t/${encodeURIComponent(project)}/${encodeURIComponent(task)}`);
  await expectTheme(page, theme);
  await page.getByRole("button", { name: "New run" }).click();
  const dialog = page.getByRole("dialog", { name: /New run/ });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio", { name: new RegExp(`^${host.name}\\b`) }).check();
  const count = dialog.getByLabel("GPUs per run", { exact: true });
  while (Number(await count.textContent()) > gpus) await dialog.getByRole("button", { name: "Fewer GPUs per run" }).click();
  while (Number(await count.textContent()) < gpus) await dialog.getByRole("button", { name: "More GPUs per run" }).click();
  await expect(count).toHaveText(String(gpus));
  // the checkbox is drawn as a switch; a user clicks its label
  const wait = dialog.getByLabel(/wait for GPUs/);
  if ((await wait.isChecked()) !== queue) await dialog.locator("label", { hasText: "wait for GPUs" }).click();
  await expect(wait).toBeChecked({ checked: queue });
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
  return made;
}

test("the launch dialog queues a run on a fake host", async ({ page, request, theme }) => {
  const target = await sshTarget(request);
  const made = await launch(page, request, theme, target, { gpus: 1, queue: true });
  const detail = await getJson<{ record: RecordLite }>(request, `/api/v1/runs/${made.run_id}`);
  // the run belongs to the host's environment (executor.host is the machine's hostname)
  expect(detail.record.environment_id).toBe(target.host.state.environment_id);

  await page.goto(`/r/${made.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(made.hypothesis);
  await expect(page.getByRole("region", { name: /Placement$/ })).toContainText(target.host.name);

  // leave the fake host's queue as it was
  const stopped = await request.post(`/api/v1/runs/${made.run_id}/stop`, { data: {} });
  expect(stopped.status()).toBe(200);
});

test("a run launched on a fake host executes its command with the seed", async ({ page, request, theme }) => {
  const target = await sshTarget(request);
  const made = await launch(page, request, theme, target, { gpus: 0, queue: false });
  expect(made.environment_id).toBe(target.host.state.environment_id);

  // the host runs `echo hx-e2e 7` and the hub mirrors the end
  await expect
    .poll(
      async () => (await getJson<{ record: RecordLite }>(request, `/api/v1/runs/${made.run_id}`)).record.status,
      { timeout: 60_000, message: "the launched run never finished" },
    )
    .toBe("finished");
  const out = await getJson<{ text: string }>(request, `/api/v1/runs/${made.run_id}/logs?stream=stdout`);
  expect(out.text).toContain("hx-e2e 7");

  await page.goto(`/r/${made.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(made.hypothesis);
});
