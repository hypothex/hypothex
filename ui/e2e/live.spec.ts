import { demoTask, expect, expectTheme, getJson, type RunLite, type TaskRunsLite, test } from "./fixtures";

/** `SEQUENCE_KEY` in `src/api/events.ts`: the last event sequence a tab saw (sessionStorage). */
const SEQUENCE_KEY = "hx-ws-sequence";

test("a note added through the API appears on the open run page without a reload", async ({
  page,
  request,
  theme,
}) => {
  const { project, task } = demoTask("generic");
  const runs = await getJson<RunLite[]>(
    request,
    `/api/v1/runs?project=${project}&task=${task}&status=finished&limit=1`,
  );
  const run = runs[0];
  if (!run) throw new Error("generic demo has no finished run");

  // The unlock page's stream is ready (it saved a sequence), so its socket is not the one
  // watched below.
  const saved = () => page.evaluate((key) => window.sessionStorage.getItem(key), SEQUENCE_KEY);
  await expect.poll(saved).not.toBeNull();

  // the newest event before the page opens: a new tab subscribes after the hub's head, not 0
  const hosts = await getJson<{ kind: string; state?: { last_sequence?: number } | null }[]>(
    request,
    "/api/v1/hosts",
  );
  const head = hosts.find((h) => h.kind === "local")?.state?.last_sequence;
  if (typeof head !== "number") throw new Error("hub row has no last_sequence");

  // Open the run page as a new tab would: without the sequence the unlock page saved in
  // this tab. Resuming there subscribes one below it, below `head` once any other event
  // (another spec's rename, a demo run) lands between that save and the read above.
  await page.addInitScript((key) => window.sessionStorage.removeItem(key), SEQUENCE_KEY);
  const sent: string[] = [];
  const received: string[] = [];
  page.on("websocket", (socket) => {
    if (!socket.url().endsWith("/api/v1/ws")) return;
    socket.on("framesent", (frame) => sent.push(String(frame.payload)));
    socket.on("framereceived", (frame) => received.push(String(frame.payload)));
  });
  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByText(run.hypothesis || run.run_id).first()).toBeVisible();
  await expect.poll(() => received.some((m) => m.includes('"type":"ready"'))).toBe(true);
  const subscribe = JSON.parse(sent[0] ?? "{}") as { type?: string; after_sequence?: number };
  expect(subscribe.type).toBe("subscribe");
  expect(subscribe.after_sequence).toBeGreaterThanOrEqual(head);
  await page.evaluate(() => {
    (window as unknown as { hxNoReload?: boolean }).hxNoReload = true;
  });

  const text = `live note ${theme} ${Date.now()}`;
  const response = await request.post(`/api/v1/runs/${run.run_id}/notes`, {
    data: { text, author: "e2e" },
  });
  expect(response.status()).toBe(200);

  await expect(page.getByText(text)).toBeVisible();
  // The CDP frame listener can lag a tick behind the socket's own onmessage handler (which
  // already ran the UI update above), so poll instead of asserting once.
  await expect
    .poll(() => received.some((m) => m.includes('"type":"run.note_added"')))
    .toBe(true);
  const stillSamePage = await page.evaluate(
    () => (window as unknown as { hxNoReload?: boolean }).hxNoReload === true,
  );
  expect(stillSamePage).toBe(true);
});

test("renaming a run updates the run page, the task sidebar and the API", async ({ page, request }) => {
  const { project, task } = demoTask("generic");
  const url = `/api/v1/tasks/${project}/${task}/runs`;
  const runOf = async (runId: string) => (await getJson<TaskRunsLite>(request, url)).runs.find((r) => r.run_id === runId);
  const data = await getJson<TaskRunsLite>(request, url);
  const run = data.runs.find((r) => !r.archived && !r.renamed);
  if (!run) throw new Error("generic demo has no unarchived run without a rename");
  const heading = page.getByRole("heading", { level: 1 });
  await page.goto(`/r/${run.run_id}`);
  await expect(heading).toContainText(run.name);
  await heading.getByRole("button", { name: "Rename" }).click();
  const input = page.getByRole("textbox", { name: "Run name" });
  await input.fill("svm, tuned C");
  await input.press("Enter");
  await expect(heading).toContainText("svm, tuned C");
  await expect.poll(() => runOf(run.run_id)).toMatchObject({ name: "svm, tuned C", renamed: true });
  await page.goto(`/t/${project}/${task}?group=run`);
  await expect(page.getByRole("complementary", { name: "Runs" }).getByText("svm, tuned C")).toBeVisible();
  // Reset name restores the derived name
  await page.goto(`/r/${run.run_id}`);
  await heading.getByRole("button", { name: "Rename" }).click();
  await page.getByRole("button", { name: "Reset name" }).click();
  await expect(heading).toContainText(run.name);
  await expect(heading).not.toContainText("svm, tuned C");
  await expect.poll(() => runOf(run.run_id)).toMatchObject({ name: run.name, renamed: false });
});
