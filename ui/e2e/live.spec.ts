import { demoTask, expect, expectTheme, getJson, type RunLite, test } from "./fixtures";

test("a note added through the API appears on the open run page without a reload", async ({
  page,
  request,
  theme,
}) => {
  const sent: string[] = [];
  const received: string[] = [];
  page.on("websocket", (socket) => {
    if (!socket.url().endsWith("/api/v1/ws")) return;
    socket.on("framesent", (frame) => sent.push(String(frame.payload)));
    socket.on("framereceived", (frame) => received.push(String(frame.payload)));
  });

  const { project, task } = demoTask("generic");
  const runs = await getJson<RunLite[]>(
    request,
    `/api/v1/runs?project=${project}&task=${task}&status=finished&limit=1`,
  );
  const run = runs[0];
  if (!run) throw new Error("generic demo has no finished run");

  // the newest event before the page opens: a new tab subscribes after the hub's head, not 0
  const hosts = await getJson<{ kind: string; state?: { last_sequence?: number } | null }[]>(
    request,
    "/api/v1/hosts",
  );
  const head = hosts.find((h) => h.kind === "local")?.state?.last_sequence;
  if (typeof head !== "number") throw new Error("hub row has no last_sequence");

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
