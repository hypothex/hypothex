import { expect, test } from "bun:test";
import { fillVars } from "../../src/launch/command";
import { launchDefaults } from "../../src/launch/draft";
import { initialHost, initialGpus } from "../../src/launch/plan";
import { makeRecord } from "../pages/fixtures";
import { launchHost, gpu } from "./fixtures";

test("template launch retains environment and GPU request even with incomplete seed history", () => {
  const out = launchDefaults(makeRecord({ environment_id: "env-remote", gpus_requested: 2 }), [], false);
  expect(out.templateEnvironment).toBe("env-remote");
  expect(out.draft.gpus).toBe(2);
  expect(out.draft.seeds).toBe("");
});
test("template host is retained while disconnected and unknown environments never fall back", () => {
  const hosts = [launchHost({ name: "local", kind: "hub" }), launchHost({ name: "gpu1", environment_id: "env-remote", state: "disabled" })];
  expect(initialHost(hosts, "toy", null, "env-remote")).toBe("gpu1");
  expect(initialHost(hosts, "toy", null, "env-missing")).toBeNull();
});
test("configured GPUs initialize the host but an explicit template zero or three wins", () => {
  const host = launchHost({ kind: "slurm", slurm: { pending: 0, running: 0, defaults: { gpus: 2, partition: null, account: null, time: "08:00:00", extra: [] } } });
  expect(initialGpus(host)).toBe(2);
  expect(initialGpus(host, 0)).toBe(0);
  expect(initialGpus(host, 3)).toBe(3);
  expect(initialGpus(launchHost({ gpus: [gpu(0)] }))).toBe(1);
});
test("preview fills only known vars, leaves seed for seed display, and preserves argv", () => {
  expect(fillVars(["python", "--config={config}", "{missing}", "{seed}"], { config: "a b.yaml", seed: "wrong" })).toEqual(["python", "--config=a b.yaml", "{missing}", "{seed}"]);
});
