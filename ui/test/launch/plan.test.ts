import { describe, expect, test } from "bun:test";

import {
  availability,
  freeGpus,
  gpuCells,
  gpuLimit,
  gpusForHost,
  hostTitle,
  launchSummary,
  pickHost,
  planLaunch,
  posRange,
  slurmBody,
  stateLabel,
  stateReason,
  toLaunchHosts,
  validSlurmTime,
} from "../../src/launch/plan";
import { DGX, GPU1, GPU2, MCCLEARY, PROJECT, gpu, hostRow, launchHost } from "./fixtures";

const NOW = Date.parse("2026-10-03T14:32:00Z");
const HOSTS = toLaunchHosts([GPU1, DGX, MCCLEARY, GPU2], { gpus: [], queue: 0 });
const [HUB_HOST, G1, DGX_HOST, SLURM_HOST, BOOT_HOST] = HOSTS;
const hub = launchHost({ name: "local", kind: "hub", projects: null });

describe("toLaunchHosts", () => {
  test("puts the hub first with its own GPUs and queue", () => {
    const hosts = toLaunchHosts([GPU1], { gpus: [gpu(0, { name: "RTX 4090" })], queue: 1 });
    expect(hosts.map((h) => [h.name, h.kind, h.state, h.queue])).toEqual([
      ["local", "hub", "connected", 1],
      ["gpu1", "ssh", "connected", 3],
    ]);
    expect(hosts[0]?.projects).toBeNull();
    expect(hosts[0]?.gpus.map((g) => g.name)).toEqual(["RTX 4090"]);
    expect(hosts[1]?.projects).toEqual([PROJECT]);
  });

  test("uses the hub's own row when the hosts list has one", () => {
    const hosts = toLaunchHosts([GPU1, hostRow("local", { queue: 2 })], { gpus: [], queue: 0 });
    expect(hosts.map((h) => h.name)).toEqual(["local", "gpu1"]);
    expect(hosts[0]).toMatchObject({ kind: "hub", queue: 2, projects: null });
  });
});

describe("availability", () => {
  test("a connected host with this project mapped can take the run; so can the hub", () => {
    expect(availability(launchHost(), PROJECT, NOW)).toEqual({ ok: true, reason: "" });
    expect(availability(hub, "any-project", NOW)).toEqual({ ok: true, reason: "" });
  });

  test("every other state names what is wrong and the fix", () => {
    const at = (over: Parameters<typeof launchHost>[0]) => stateReason(launchHost(over), NOW);
    expect(at({ state: "stale", since: "2026-10-03T14:28:00Z" })).toBe("gpu1 stale 4m: no heartbeat");
    expect(at({ state: "connecting" })).toBe("connecting to gpu1");
    expect(at({ state: "bootstrapping" })).toBe("installing hx on gpu1");
    expect(at({ state: "bootstrapping", message: "3/5 uv" })).toBe("installing hx on gpu1: 3/5 uv");
    expect(at({ state: "upgrade" })).toBe("hx on gpu1 needs an upgrade: hx hosts upgrade gpu1");
    expect(at({ state: "error", message: "ssh: connect to host gpu1 port 22: Connection refused" })).toBe(
      "ssh: connect to host gpu1 port 22: Connection refused",
    );
    expect(at({ state: "error" })).toBe("gpu1: connection error");
    expect(at({ state: "disabled" })).toBe("gpu1 disconnected: hx hosts connect gpu1");
    expect(availability(launchHost({ state: "disabled" }), PROJECT, NOW).ok).toBe(false);
  });

  test("a host without this project's repo mapped names hx hosts map", () => {
    expect(availability(launchHost({ name: "gpu3", projects: ["other"] }), PROJECT, NOW)).toEqual({
      ok: false,
      reason: "no path for rxn-forward on gpu3: hx hosts map rxn-forward gpu3 <path>",
    });
  });
});

test("two hubs bootstrapping one host: the second waits, then shows the lock error, and never launches there", () => {
  // while it waits on the install lock, the backend says bootstrapping with an empty message
  const waiting = launchHost({ state: "bootstrapping" });
  expect(availability(waiting, PROJECT, NOW)).toEqual({ ok: false, reason: "installing hx on gpu1" });
  expect(stateLabel(waiting, NOW)).toBe("boot");
  // a lock held too long ends the bootstrap: state error with the BootstrapError message
  const lock = "lock /home/sv/.hypothex/runtime/.lock is held by hub2:4411; waited 300s";
  const locked = launchHost({ state: "error", message: lock });
  expect(availability(locked, PROJECT, NOW)).toEqual({ ok: false, reason: lock });
  expect(stateLabel(locked, NOW)).toBe("error");
  expect(pickHost([waiting], PROJECT, "gpu1", NOW)).toBeNull();
  expect(pickHost([locked, launchHost({ name: "gpu3" })], PROJECT, "gpu1", NOW)).toBe("gpu3");
});

test("stateLabel is short", () => {
  const label = (over: Parameters<typeof launchHost>[0]) => stateLabel(launchHost(over), NOW);
  expect(label({ state: "stale", since: "2026-10-03T14:28:00Z" })).toBe("stale 4m");
  expect(label({ state: "stale", since: "2026-10-03T13:02:00Z" })).toBe("stale 1h");
  expect(label({ state: "stale", since: "2026-09-30T14:32:00Z" })).toBe("stale 3d");
  expect(label({ state: "stale", since: null })).toBe("stale");
  expect(label({ state: "bootstrapping" })).toBe("boot");
  expect(label({ state: "disabled" })).toBe("off");
  expect(label({ state: "connecting" })).toBe("connecting");
  expect(label({ state: "upgrade" })).toBe("upgrade");
  expect(label({ state: "error" })).toBe("error");
});

test("freeGpus and gpuCells read nvidia-smi rows in index order", () => {
  expect(freeGpus(G1)).toEqual([5]);
  expect(gpuCells(G1)).toEqual(["busy", "busy", "busy", "other", "busy", "free", "busy", "other"]);
  // the hub sends no GPUs for a host that is not connected
  expect(gpuCells(DGX_HOST)).toEqual([]);
  expect(gpuCells(BOOT_HOST)).toEqual([]);
  // a stale host's last known GPUs (kept by useHosts / the launch hosts query) are drawn stale
  expect(gpuCells({ ...DGX_HOST, gpus: [gpu(0, { run_id: "r-d0" }), gpu(1)] })).toEqual(["stale", "stale"]);
  expect(gpuCells({ ...BOOT_HOST, gpus: [gpu(0), gpu(1)] })).toEqual(["none", "none"]);
  expect(freeGpus(launchHost({ gpus: [gpu(3), gpu(1, { run_id: "r" }), gpu(0)] }))).toEqual([0, 3]);
  expect(freeGpus(SLURM_HOST)).toEqual([]);
});

test("gpuLimit and gpusForHost keep the stepper inside the host", () => {
  expect(gpuLimit(G1)).toBe(8);
  expect(gpuLimit(HUB_HOST)).toBe(0);
  expect(gpuLimit(SLURM_HOST)).toBe(8);
  // a 0 forced by a GPU-less host goes back to 1 on a GPU host; a chosen 0 (a CPU run) stays
  expect(gpusForHost(0, G1, HUB_HOST)).toBe(1);
  expect(gpusForHost(0, G1)).toBe(0);
  expect(gpusForHost(0, G1, G1)).toBe(0);
  expect(gpusForHost(0, SLURM_HOST, G1)).toBe(0);
  expect(gpusForHost(5, launchHost({ gpus: [gpu(0), gpu(1)] }))).toBe(2);
  expect(gpusForHost(3, HUB_HOST)).toBe(0);
  expect(gpusForHost(4, SLURM_HOST)).toBe(4);
});

describe("planLaunch", () => {
  test("ssh host with the queue on: seeds that do not fit wait behind the queue", () => {
    expect(planLaunch(G1, 1, 3, true)).toEqual({ now: 1, queued: 2, blocked: 0, cvd: [5], firstPos: 4 });
    expect(planLaunch(G1, 2, 3, true)).toEqual({ now: 0, queued: 3, blocked: 0, cvd: [], firstPos: 4 });
    expect(planLaunch(G1, 1, 1, true)).toEqual({ now: 1, queued: 0, blocked: 0, cvd: [5], firstPos: null });
  });

  test("queue off, no GPUs, SLURM, and the hub", () => {
    expect(planLaunch(G1, 1, 3, false)).toEqual({ now: 1, queued: 0, blocked: 2, cvd: [5], firstPos: null });
    expect(planLaunch(G1, 0, 3, true)).toEqual({ now: 3, queued: 0, blocked: 0, cvd: [], firstPos: null });
    expect(planLaunch(SLURM_HOST, 2, 3, true)).toEqual({ now: 0, queued: 3, blocked: 0, cvd: [], firstPos: null });
    const gpuHub = launchHost({ name: "local", kind: "hub", projects: null, gpus: [gpu(0), gpu(1)] });
    expect(planLaunch(gpuHub, 1, 3, true)).toEqual({ now: 2, queued: 0, blocked: 1, cvd: [0], firstPos: null });
  });
});

test("posRange", () => {
  expect(posRange({ now: 1, queued: 2, blocked: 0, cvd: [5], firstPos: 4 })).toBe("pos 4–5");
  expect(posRange({ now: 0, queued: 1, blocked: 0, cvd: [], firstPos: 4 })).toBe("pos 4");
  expect(posRange({ now: 3, queued: 0, blocked: 0, cvd: [], firstPos: null })).toBe("");
});

test("pickHost: the preferred host if it can take the run, else the most free GPUs", () => {
  expect(pickHost(HOSTS, PROJECT, null)).toBe("gpu1");
  expect(pickHost(HOSTS, PROJECT, "mccleary")).toBe("mccleary");
  expect(pickHost(HOSTS, PROJECT, "dgx")).toBe("gpu1");
  expect(pickHost(HOSTS, "other-project", null)).toBe("local");
  expect(pickHost([], PROJECT, null)).toBeNull();
});

test("launchSummary", () => {
  expect(launchSummary(G1, 1, 3, "02:00:00")).toBe("3 × 1 GPU on gpu1");
  expect(launchSummary(SLURM_HOST, 2, 1, " 08:00:00 ")).toBe("1 job × 2 GPU, ≤ 08:00:00");
  expect(launchSummary(SLURM_HOST, 2, 3, "08:00:00")).toBe("3 jobs × 2 GPU, ≤ 08:00:00");
  // time left blank: the host's default time applies
  expect(launchSummary(SLURM_HOST, 2, 3, " ")).toBe("3 jobs × 2 GPU");
  expect(launchSummary(HUB_HOST, 0, 3, "02:00:00")).toBe("3 runs on local, no GPU");
  expect(launchSummary(HUB_HOST, 0, 1, "02:00:00")).toBe("1 run on local, no GPU");
});

test("validSlurmTime accepts every sbatch --time form; slurmBody sends only the fields filled in", () => {
  for (const ok of ["08:00:00", "1-12:00:00", "30", "90:00", "2-0", "2-04:30"]) {
    expect(validSlurmTime(ok)).toBe(true);
  }
  for (const bad of ["8h", "", "1:2:3:4", "08:00:0", "-1"]) expect(validSlurmTime(bad)).toBe(false);
  expect(slurmBody({ partition: " gpu ", account: "", time: " 08:00:00 " }, 2)).toEqual({
    partition: "gpu",
    time: "08:00:00",
    gpus: 2,
  });
  // blank means the host's default: the key is left out, so the backend keeps the host's value
  const blank = slurmBody({ partition: "", account: " ", time: "" }, 2);
  expect(blank).toEqual({ gpus: 2 });
  expect(["partition", "account", "time", "extra"].filter((k) => k in blank)).toEqual([]);
});

test("hostTitle", () => {
  expect(hostTitle(G1)).toBe("gpu1: 8 GPU (A100 80GB), 1 free, 3 queued");
  expect(hostTitle(SLURM_HOST)).toBe("mccleary: 4 running, 6 pending in SLURM");
  expect(hostTitle(HUB_HOST)).toBe("local: 0 GPU, 0 free, 0 queued");
});
