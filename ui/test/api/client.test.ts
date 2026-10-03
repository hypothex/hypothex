import { afterEach, describe, expect, test } from "bun:test";

import { ApiError, api, buildUrl, wsUrl } from "../../src/api/client";
import { mockFetch } from "./fetch-mock";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

describe("buildUrl", () => {
  test("encodes path parameters, repeats array query keys, drops undefined", () => {
    const url = buildUrl(
      "/api/v1/tasks/{project}/{task}/leaderboard",
      { project: "toy", task: "a b/c" },
      { metric: ["accuracy@v1", "f1@v2"], since: undefined, limit: 5, archived: false },
    );
    expect(url).toBe(
      "/api/v1/tasks/toy/a%20b%2Fc/leaderboard?metric=accuracy%40v1&metric=f1%40v2&limit=5&archived=false",
    );
  });

  test("returns the bare path when there is no query", () => {
    expect(buildUrl("/api/v1/projects")).toBe("/api/v1/projects");
  });

  test("throws on a missing path parameter", () => {
    expect(() => buildUrl("/api/v1/runs/{run_id}", {})).toThrow('missing path parameter "run_id"');
  });
});

describe("api", () => {
  test("leaderboard GETs the task route with repeated metric params", async () => {
    const calls = mockFetch({ project: "toy", task: "acc", rows: [] });
    const board = await api.leaderboard("toy", "acc", ["accuracy@v2"]);
    expect(board.task).toBe("acc");
    expect(calls).toEqual([
      { url: "/api/v1/tasks/toy/acc/leaderboard?metric=accuracy%40v2", method: "GET", body: undefined },
    ]);
  });

  test("overview passes since only when given", async () => {
    const calls = mockFetch({ headline: "Idle." });
    await api.overview();
    await api.overview("2026-09-27T00:00:00Z");
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/overview",
      "/api/v1/overview?since=2026-09-27T00%3A00%3A00Z",
    ]);
  });

  test("saveView PUTs the YAML text with a command id", async () => {
    const calls = mockFetch({ info: { name: "route" }, view: { title: "route quality" } });
    const saved = await api.saveView("toy", "acc", "route", "title: route quality\n", { command_id: "c-1" });
    expect(saved.view.title).toBe("route quality");
    expect(calls[0]).toEqual({
      url: "/api/v1/tasks/toy/acc/views/route",
      method: "PUT",
      body: { text: "title: route quality\n", command_id: "c-1" },
    });
  });

  test("queryView POSTs the body as JSON", async () => {
    const calls = mockFetch({ panels: [{ type: "markdown", title: "", rows: [], meta: { text: "hi" } }] });
    const out = await api.queryView("toy", "acc", { name: "overview" });
    expect(out.panels[0]?.meta.text).toBe("hi");
    expect(calls[0]).toEqual({ url: "/api/v1/tasks/toy/acc/views/query", method: "POST", body: { name: "overview" } });
  });

  test("runTrace encodes the example id", async () => {
    const calls = mockFetch({ type: "trace", title: "", rows: [], meta: {} });
    await api.runTrace("r1", "ex/1 a");
    expect(calls[0]?.url).toBe("/api/v1/runs/r1/traces/ex%2F1%20a");
  });

  test("compareExamples sends field only when given", async () => {
    const calls = mockFetch({ fixed: [], broken: [] });
    await api.compareExamples("r1", "r2", "solved@v2");
    await api.compareExamples("r1", "r2", "accuracy", "correct");
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/compare/examples?a=r1&b=r2&metric=solved%40v2",
      "/api/v1/compare/examples?a=r1&b=r2&metric=accuracy&field=correct",
    ]);
  });

  test("actions send a fresh command id and created_by human", async () => {
    const calls = mockFetch({ run_id: "r2" });
    await api.rerun("r1");
    await api.rerun("r1");
    const [a, b] = calls.map((c) => c.body as { command_id: string; created_by: string });
    expect(a?.created_by).toBe("human");
    expect(a?.command_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(a?.command_id).not.toBe(b?.command_id);
  });

  test("reinfer and note carry their own fields", async () => {
    const calls = mockFetch({ ok: true });
    await api.reinfer("r1", "ckpt-3", { command_id: "r" });
    await api.note("r1", "looks good", { command_id: "n" });
    expect(calls[0]?.body).toEqual({ command_id: "r", created_by: "human", checkpoint: "ckpt-3" });
    expect(calls[1]?.body).toEqual({ command_id: "n", created_by: "human", text: "looks good", author: "human" });
  });
});

describe("errors", () => {
  test("400 with issues keeps message, type and issues", async () => {
    const issue = { line: 3, path: "panels[0].data.metrics[0]", message: "unknown metric accuracyy", suggestion: "accuracy" };
    mockFetch({ error: "invalid view", issues: [issue] }, 400);
    const err = (await api.saveView("toy", "acc", "v", "x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    expect(err.message).toBe("invalid view");
    expect(err.issues).toEqual([issue]);
  });

  test("404 keeps the server error type", async () => {
    mockFetch({ error: "run nope not found", type: "RunNotFoundError" }, 404);
    const err = (await api.run("nope").catch((e: unknown) => e)) as ApiError;
    expect([err.status, err.type, err.message]).toEqual([404, "RunNotFoundError", "run nope not found"]);
  });

  test("422 from FastAPI names the first bad field", async () => {
    mockFetch({ detail: [{ loc: ["body", "text"], msg: "Field required", type: "missing" }] }, 422);
    const err = (await api.validateView("toy", "acc", "").catch((e: unknown) => e)) as ApiError;
    expect(err.message).toBe("body.text: Field required");
    expect(err.type).toBe("RequestValidationError");
  });

  test("a non-JSON error body becomes HTTP <status>: <text>", async () => {
    mockFetch("Bad Gateway", 502);
    const err = (await api.projects().catch((e: unknown) => e)) as ApiError;
    expect(err.message).toBe("HTTP 502: Bad Gateway");
  });

  test("an unreachable server is status 0 NetworkError", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const err = (await api.projects().catch((e: unknown) => e)) as ApiError;
    expect([err.status, err.type, err.message]).toEqual([0, "NetworkError", "Cannot reach hx serve"]);
  });
});

test("wsUrl points at the event stream on the page origin", () => {
  expect(wsUrl()).toBe("ws://127.0.0.1:7777/api/v1/ws");
});
