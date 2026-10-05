import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient } from "@tanstack/react-query";

import type { RunRecord } from "../../src/api/models";
import { ApiError } from "../../src/api/client";
import { auth } from "../../src/api/auth";
import { fetchLaunchHosts, launchRequest, launchSeeds, outcomeUnknown, seedCommandId } from "../../src/launch/launchApi";
import { type LaunchSpec, gpuCells } from "../../src/launch/plan";
import { makeRecord } from "../pages/fixtures";
import { type Call, HttpReply, mockApi, restoreFetch } from "../pages/helpers";
import { GPU1, gpu, hostRow, launchHost } from "./fixtures";

afterEach(() => {
  restoreFetch();
  auth.select(null);
});

const SPEC: LaunchSpec = {
  host: launchHost(),
  project: "rxn-forward",
  repo: "/Users/sv/code/rxn-forward",
  commit: null,
  task: "uspto-forward-top1",
  argv: ["python", "train.py", "--seed", "{seed}"],
  hypothesis: " beam 10 holds ",
  gpus: 1,
  queue: true,
  slurm: null,
  params: { lr: "3e-4" },
  vars: {},
};
const rec = (seed: number): RunRecord =>
  makeRecord({ run_id: `20261003-120000-uspto-forward-top1-s${seed}`, seed, status: "queued" });
const seedOf = (call: Call): number => (call.body as { seed: number }).seed;
const idOf = (call: Call): string => (call.body as { command_id: string }).command_id;

test("a launch network retry cannot continue with a replacement credential", async () => {
  auth.select("old-synthetic");
  let attempts = 0;
  mockApi({ "POST /api/v1/hosts/gpu1/runs": () => {
    attempts += 1;
    if (attempts === 1) throw new TypeError("connection reset");
    return rec(1);
  } });
  const pending = launchSeeds(SPEC, [1, 2], "attempt", { delayMs: 50 });
  await new Promise((resolve) => setTimeout(resolve, 10));
  expect(attempts).toBe(1);
  auth.accept(auth.select("new-synthetic"));
  const result = await pending;
  expect(attempts).toBe(1);
  expect(result.records).toEqual([]);
  expect(result.failed?.error.name).toBe("AbortError");
});

describe("fetchLaunchHosts", () => {
  test("puts the hub first with its own GPUs and queue", async () => {
    mockApi({
      "GET /api/v1/hosts": [GPU1],
      "GET /api/v1/gpus": [gpu(0, { name: "RTX 4090" })],
      "GET /api/v1/queue": [{ run_id: "r1", position: 1, gpus_requested: 1 }],
    });
    const hosts = await fetchLaunchHosts();
    expect(hosts.map((h) => [h.name, h.kind, h.queue])).toEqual([
      ["local", "hub", 1],
      ["gpu1", "ssh", 3],
    ]);
    expect(hosts[0]?.gpus.map((g) => g.name)).toEqual(["RTX 4090"]);
  });

  test("a hub without the env routes still lists itself, with no GPUs", async () => {
    mockApi({ "GET /api/v1/hosts": [] });
    expect(await fetchLaunchHosts()).toEqual([
      {
        name: "local",
        kind: "hub",
        state: "connected",
        since: null,
        message: "",
        gpus: [],
        queue: 0,
        slurm: null,
        projects: null,
      },
    ]);
  });

  test("uses the hub's own row when the hosts list has one", async () => {
    mockApi({
      "GET /api/v1/hosts": [hostRow("local", { queue: 2 }), GPU1],
      "GET /api/v1/gpus": [],
      "GET /api/v1/queue": [],
    });
    const hosts = await fetchLaunchHosts();
    expect(hosts.map((h) => h.name)).toEqual(["local", "gpu1"]);
    expect(hosts[0]).toMatchObject({ kind: "hub", queue: 2, projects: null });
  });

  test("a failing hosts list is an error", async () => {
    mockApi({ "GET /api/v1/hosts": new HttpReply(500, { error: "hub index locked", type: "IndexError" }) });
    await expect(fetchLaunchHosts()).rejects.toThrow("hub index locked");
  });

  test("with the query client, a stale host keeps the GPUs and queue it had while connected", async () => {
    const qc = new QueryClient();
    const hub = { "GET /api/v1/gpus": [], "GET /api/v1/queue": [] };
    mockApi({ ...hub, "GET /api/v1/hosts": [GPU1] });
    expect((await fetchLaunchHosts(undefined, qc))[1]?.gpus).toHaveLength(8);
    // the hub sends no GPUs and queue 0 once the host is stale
    const stale = { ...GPU1, gpus: [], queue: 0, state: { ...GPU1.state, state: "stale" as const } };
    mockApi({ ...hub, "GET /api/v1/hosts": [stale] });
    const hosts = await fetchLaunchHosts(undefined, qc);
    expect([hosts[1]?.state, hosts[1]?.gpus.length, hosts[1]?.queue]).toEqual(["stale", 8, 3]);
    expect(gpuCells(hosts[1] ?? launchHost())).toEqual(Array(8).fill("stale"));
  });
});

test("launchRequest: a host launch names the project, never a path; the hub gets its repo", () => {
  expect(launchRequest(SPEC, 4)).toEqual({
    project: "rxn-forward",
    task: "uspto-forward-top1",
    command: ["python", "train.py", "--seed", "{seed}"],
    hypothesis: "beam 10 holds",
    seed: 4,
    tags: [],
    params: { lr: "3e-4" },
    vars: {},
    gpus: 1,
    queue: true,
  });
  const slurm = launchRequest(
    {
      ...SPEC,
      host: launchHost({ name: "mccleary", kind: "slurm" }),
      gpus: 2,
      slurm: { partition: "", account: "lab", time: "08:00:00" },
    },
    4,
  );
  expect(slurm.queue).toBe(false);
  expect(slurm.slurm).toEqual({ account: "lab", time: "08:00:00", gpus: 2 });
  const hub = launchRequest({ ...SPEC, host: launchHost({ name: "local", kind: "hub", projects: null }), gpus: 0 }, 4);
  expect(hub.queue).toBe(false);
  expect("slurm" in hub).toBe(false);
  expect(["repo" in hub, "project" in hub]).toEqual([true, false]);
  expect((hub as { repo: string }).repo).toBe("/Users/sv/code/rxn-forward");
  // the hub pins its own checkout unless the spec pins a commit; the dialog never sends a diff
  expect(["commit" in hub, "diff" in hub]).toEqual([false, false]);
  const sha = "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37";
  const pinned = launchRequest({ ...SPEC, commit: sha }, 4);
  expect([pinned.commit, "repo" in pinned, "diff" in pinned]).toEqual([sha, false, false]);
});

test("a blank-field SLURM launch body has no partition, account, time or extra keys", () => {
  // the backend merges the body over the host's SlurmDefaults (exclude_unset): any key sent,
  // even null, would wipe the host's partition, account, time or extra #SBATCH lines
  const body = launchRequest(
    {
      ...SPEC,
      host: launchHost({ name: "mccleary", kind: "slurm" }),
      gpus: 2,
      slurm: { partition: "", account: "", time: "" },
    },
    4,
  );
  expect(body.slurm).toEqual({ gpus: 2 });
  expect(Object.keys(body.slurm ?? {})).toEqual(["gpus"]);
});

describe("launchSeeds", () => {
  test("posts one run per seed, in order, each with its own stable command_id", async () => {
    const calls = mockApi({ "POST /api/v1/hosts/gpu1/runs": (call: Call) => rec(seedOf(call)) });
    const progress: number[] = [];
    const out = await launchSeeds(SPEC, [4, 5, 6], "base", { onProgress: (done) => progress.push(done) });
    expect(out.failed).toBeNull();
    expect(out.records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(calls.map(idOf)).toEqual(["base.s4", "base.s5", "base.s6"]);
    expect((calls[0]?.body as { created_by: string }).created_by).toBe("human");
    expect(progress).toEqual([1, 2, 3]);
    expect(seedCommandId("base", 4)).toBe("base.s4");
  });

  test("the hub launches through POST /api/v1/runs", async () => {
    const calls = mockApi({ "POST /api/v1/runs": (call: Call) => rec(seedOf(call)) });
    const hub = { ...SPEC, host: launchHost({ name: "local", kind: "hub", projects: null }) };
    await launchSeeds(hub, [1], "base");
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/runs"]);
  });

  test("stops at the first refused seed and reports it; a 4xx is not retried", async () => {
    const calls = mockApi({
      "POST /api/v1/hosts/gpu1/runs": (call: Call) =>
        seedOf(call) === 5
          ? new HttpReply(400, { error: "asked for 2 GPUs; this host has 1", type: "RunError" })
          : rec(seedOf(call)),
    });
    const out = await launchSeeds(SPEC, [4, 5, 6], "base", { delayMs: 0 });
    expect(out.records.map((r) => r.seed)).toEqual([4]);
    expect(out.failed?.seed).toBe(5);
    expect(out.failed?.error.message).toBe("asked for 2 GPUs; this host has 1");
    expect(out.failed?.unknown).toBe(false);
    expect(calls.map(idOf)).toEqual(["base.s4", "base.s5"]);
  });

  test("retries a dropped request with the same command_id", async () => {
    let drops = 1;
    const calls = mockApi({
      "POST /api/v1/hosts/gpu1/runs": (call: Call) => {
        if (drops > 0) {
          drops -= 1;
          throw new Error("socket closed");
        }
        return rec(seedOf(call));
      },
    });
    const out = await launchSeeds(SPEC, [4], "base", { delayMs: 0 });
    expect(out.failed).toBeNull();
    expect(calls.map(idOf)).toEqual(["base.s4", "base.s4"]);
  });

  test("gives up after three unanswered tries", async () => {
    const calls = mockApi({
      "POST /api/v1/hosts/gpu1/runs": () => {
        throw new Error("socket closed");
      },
    });
    const out = await launchSeeds(SPEC, [4, 5], "base", { delayMs: 0 });
    expect(calls).toHaveLength(3);
    expect(out.records).toEqual([]);
    expect(out.failed?.seed).toBe(4);
    expect(out.failed?.error.message).toBe("Cannot reach hx serve");
    // the server may have started seed 4 before the answer was lost
    expect(out.failed?.unknown).toBe(true);
  });

  test("a seed whose first try got no answer stays unknown when a retry is then refused", async () => {
    // try 1 starts seed 4 and its answer is lost; the hub then drops its connection to gpu1
    let tries = 0;
    mockApi({
      "POST /api/v1/hosts/gpu1/runs": () => {
        tries += 1;
        if (tries === 1) throw new Error("socket closed");
        return new HttpReply(503, { error: "gpu1 is not connected", type: "HostUnavailableError" });
      },
    });
    const out = await launchSeeds(SPEC, [4, 5], "base", { delayMs: 0 });
    expect(tries).toBe(2);
    expect(out.failed?.seed).toBe(4);
    expect(out.failed?.error.message).toBe("gpu1 is not connected");
    expect(out.failed?.unknown).toBe(true);
  });
});

test("outcomeUnknown: only an answer that says the run was not started is a refusal", () => {
  const err = (status: number, type: string): ApiError => new ApiError(status, "x", type, [], null);
  // no answer, a lost forward, an interrupted command: the run may exist
  expect(outcomeUnknown(new Error("socket closed"))).toBe(true);
  expect(outcomeUnknown(err(0, "NetworkError"))).toBe(true);
  expect(outcomeUnknown(err(503, "EnvUnreachableError"))).toBe(true);
  expect(outcomeUnknown(err(502, "HTTPError"))).toBe(true);
  expect(outcomeUnknown(err(500, "IndexError"))).toBe(true);
  expect(outcomeUnknown(err(409, "CommandInterruptedError"))).toBe(true);
  // refused before anything started
  expect(outcomeUnknown(err(400, "RunError"))).toBe(false);
  expect(outcomeUnknown(err(422, "RequestValidationError"))).toBe(false);
  expect(outcomeUnknown(err(409, "ConflictError"))).toBe(false);
  // the hub had no connection to the host: nothing was forwarded
  expect(outcomeUnknown(err(503, "HostUnavailableError"))).toBe(false);
});
