import { afterEach, describe, expect, test } from "bun:test";

import { ApiError, api, buildUrl, wsUrl } from "../../src/api/client";
import { mockFetch } from "./fetch-mock";
import { GPU1_STATE, HOSTS, SWEEP, SWEEP_LIST } from "./phase2-fixtures";

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
  test("queued cancellation carries the atomic queue precondition; Stop does not", async () => {
    const calls = mockFetch({ run_id: "r1", status: "killed" });
    await api.cancelQueuedRun("r1", { command_id: "cancel-1" });
    await api.stop("r1", { command_id: "stop-1" });
    expect(calls[0]).toEqual({ url: "/api/v1/runs/r1/stop", method: "POST", body: { command_id: "cancel-1", created_by: "human", only_queued: true } });
    expect(calls[1]?.body).toEqual({ command_id: "stop-1", created_by: "human" });
  });
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

describe("phase 2 api", () => {
  test("the sweep fixture includes every backend status count and its total", () => {
    expect(SWEEP.counts).toEqual({ finished: 4, running: 1, queued: 1, failed: 0, killed: 0, lost: 0, total: 6 });
    expect(SWEEP.counts.total).toBe(SWEEP.run_ids.length);
    expect(SWEEP_LIST[0]?.n_runs).toBe(SWEEP.counts.total);
  });

  test("every phase 2 write without options gets a fresh command id and human attribution", async () => {
    const calls = mockFetch({});
    const writes = [
      () => api.connectHost("gpu1"),
      () => api.launch({ repo: "/tmp/toy", command: ["echo", "ok"] }),
      () => api.launchOnHost("gpu1", { project: "toy", command: ["echo", "ok"] }),
      () => api.cancelQueued("toy", "s-7f3a"),
      () => api.extendSweep("toy", "s-7f3a", [4]),
      () => api.pull("r-9", "checkpoint"),
    ];
    for (const write of writes) { await write(); await write(); }
    const bodies = calls.map((call) => call.body as { command_id: string; created_by: string });
    expect(calls).toHaveLength(12);
    for (const body of bodies) {
      expect(body.command_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
      expect(body.created_by).toBe("human");
    }
    expect(new Set(bodies.map((body) => body.command_id)).size).toBe(calls.length);
    expect(calls[8]?.body).toMatchObject({ seeds: [4] });
    expect(calls[10]?.body).toMatchObject({ artifact: "checkpoint" });
  });
  test("hosts GETs the hub's own row and every host with its state, GPUs and queue", async () => {
    const calls = mockFetch(HOSTS);
    const rows = await api.hosts();
    expect(rows.map((r) => [r.name, r.kind, r.state.state, r.gpus.length, r.queue, r.slurm?.pending ?? null])).toEqual([
      ["local", "local", "connected", 0, 0, null],
      ["gpu1", "ssh", "connected", 3, 3, null],
      ["mccleary", "slurm", "connected", 0, 0, 6],
      ["dgx", "ssh", "stale", 0, 0, null],
    ]);
    expect(calls).toEqual([{ url: "/api/v1/hosts", method: "GET", body: undefined }]);
  });

  test("connectHost POSTs the given command id", async () => {
    const calls = mockFetch(GPU1_STATE);
    const state = await api.connectHost("gpu1", { command_id: "c-1" });
    expect([state.state, state.local_port]).toEqual(["connected", 51234]);
    expect(calls).toEqual([
      { url: "/api/v1/hosts/gpu1/connect", method: "POST", body: { command_id: "c-1", created_by: "human" } },
    ]);
  });

  test("launch POSTs a hub run to /api/v1/runs", async () => {
    const calls = mockFetch({ run_id: "r-1", status: "running" });
    const run = await api.launch(
      { repo: "/Users/sv/code/toy", task: "acc", stage: "train", hypothesis: "baseline", seed: 1 },
      { command_id: "l-0" },
    );
    expect(run.run_id).toBe("r-1");
    expect(calls[0]).toEqual({
      url: "/api/v1/runs",
      method: "POST",
      body: {
        command_id: "l-0",
        created_by: "human",
        repo: "/Users/sv/code/toy",
        task: "acc",
        stage: "train",
        hypothesis: "baseline",
        seed: 1,
      },
    });
  });

  test("launchOnHost sends the project by name with gpus, queue, slurm, commit and diff", async () => {
    const calls = mockFetch({ run_id: "r-9", status: "queued", executor: { type: "slurm", queue_position: 2 } });
    const run = await api.launchOnHost(
      "mccleary",
      {
        project: "toy",
        task: "acc",
        command: ["python", "train.py", "--lr", "3e-4"],
        hypothesis: "lr 3e-4 converges faster",
        gpus: 2,
        queue: true,
        slurm: { partition: "gpu", time: "04:00:00" },
        commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
        diff: "diff --git a/train.py b/train.py\n",
      },
      { command_id: "l-1" },
    );
    expect([run.status, run.executor.queue_position]).toEqual(["queued", 2]);
    expect(calls[0]).toEqual({
      url: "/api/v1/hosts/mccleary/runs",
      method: "POST",
      body: {
        command_id: "l-1",
        created_by: "human",
        project: "toy",
        task: "acc",
        command: ["python", "train.py", "--lr", "3e-4"],
        hypothesis: "lr 3e-4 converges faster",
        gpus: 2,
        queue: true,
        slurm: { partition: "gpu", time: "04:00:00" },
        commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
        diff: "diff --git a/train.py b/train.py\n",
      },
    });
    // a host launch never carries a path on this machine
    expect("repo" in (calls[0]?.body as Record<string, unknown>)).toBe(false);
  });

  test("a host that is down surfaces the hub's error type and message", async () => {
    mockFetch({ error: "host dgx is stale", type: "HostUnavailableError" }, 503);
    const err = (await api.launchOnHost("dgx", { project: "toy" }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.type, err.message]).toEqual([503, "HostUnavailableError", "host dgx is stale"]);
  });

  test("sweep and projectSweeps encode the project and sweep id", async () => {
    const first = mockFetch(SWEEP);
    const one = await api.sweep("my proj", "s-7f3a");
    const second = mockFetch(SWEEP_LIST);
    const list = await api.projectSweeps("my proj");
    expect(one.best?.params).toEqual({ lr: "3e-4", beam: "10" });
    expect(list.map((s) => [s.id, s.n_runs, s.best?.mean])).toEqual([["s-7f3a", 6, 0.9121]]);
    expect([...first, ...second].map((c) => c.url)).toEqual([
      "/api/v1/sweeps/my%20proj/s-7f3a",
      "/api/v1/projects/my%20proj/sweeps",
    ]);
  });

  test("cancelQueued and extendSweep POST to the sweep's action routes", async () => {
    const calls = mockFetch(SWEEP);
    await api.cancelQueued("toy", "s-7f3a", { command_id: "k-1" });
    await api.extendSweep("toy", "s-7f3a", [4, 5], { command_id: "e-1" });
    expect(calls).toEqual([
      {
        url: "/api/v1/sweeps/toy/s-7f3a/cancel_queued",
        method: "POST",
        body: { command_id: "k-1", created_by: "human" },
      },
      {
        url: "/api/v1/sweeps/toy/s-7f3a/extend",
        method: "POST",
        body: { command_id: "e-1", created_by: "human", seeds: [4, 5] },
      },
    ]);
  });

  test("gpus and queue GET the hub's own GPUs and queue", async () => {
    // gpu1's three GPUs as the body (HOSTS[0] is the hub's own row, which has none)
    const first = mockFetch(HOSTS[1]?.gpus ?? []);
    const gpus = await api.gpus();
    const second = mockFetch([{ run_id: "r-1", position: 1, gpus_requested: 2 }]);
    const queue = await api.queue();
    expect([gpus.length, queue[0]?.position]).toEqual([3, 1]);
    expect([...first, ...second].map((c) => [c.url, c.method])).toEqual([
      ["/api/v1/gpus", "GET"],
      ["/api/v1/queue", "GET"],
    ]);
  });

  test("pull POSTs the artifact and returns the hub path", async () => {
    const calls = mockFetch({ local_path: "/Users/sv/.hypothex/store/toy/runs/r-9/pulled/model.pt" });
    const out = await api.pull("r-9", "checkpoint", { command_id: "p-1" });
    expect(out.local_path).toBe("/Users/sv/.hypothex/store/toy/runs/r-9/pulled/model.pt");
    expect(calls[0]).toEqual({
      url: "/api/v1/runs/r-9/pull",
      method: "POST",
      body: { command_id: "p-1", created_by: "human", artifact: "checkpoint" },
    });
  });
});

test("wsUrl points at the event stream on the page origin", () => {
  expect(wsUrl()).toBe("ws://127.0.0.1:7777/api/v1/ws");
});

test("leaderboard primary selection is sent without changing secondary metric requests", async () => {
  const calls = mockFetch({ rows: [] });
  await api.leaderboard("toy", "acc", ["accuracy@v2"], undefined, "latency/p95");
  expect(calls[0]?.url).toBe("/api/v1/tasks/toy/acc/leaderboard?metric=accuracy%40v2&primary=latency%2Fp95");
});

test("bound example comparison opts in without altering legacy requests", async () => {
  const calls = mockFetch({ fixed: [], broken: [] });
  await api.compareExamples("r1", "r2", "accuracy@v1", "correct", undefined, true);
  expect(calls[0]?.url).toBe("/api/v1/compare/examples?a=r1&b=r2&metric=accuracy%40v1&field=correct&require_bound=true");
});
