import { describe, expect, test } from "bun:test";
import type { TaskRun } from "../../src/api/models";
import { globMatch, parseFilter, tokenize } from "../../src/lib/runFilter";

function run(over: Partial<TaskRun> = {}): TaskRun {
  return {
    run_id: "20261015-145600-uspto-2d2f", name: "lr 3e-4 · beam 10", derived_name: "lr 3e-4 · beam 10", renamed: false,
    group_id: "g1", seed: 2, status: "finished", end_reason: null, exit_code: 0, created_by: "agent:tuner",
    created_at: "2026-10-15T14:56:00Z", started_at: null, ended_at: null, host: "gpu1", commit: "3f2a9c1",
    params: { lr: "3e-4", beam: "10", model: "resnet50" }, tags: ["sweep", "final"], archived: false,
    starred: false, sweep_id: "s-7f3a", scores: {}, primary: 0.91, progress: 1, gpu_hours: 4.4, cost_usd: 5.3,
    ...over,
  };
}

const keep = (text: string, runs: TaskRun[]) => runs.filter(parseFilter(text)).map((r) => r.run_id);

describe("parseFilter", () => {
  test("an empty filter keeps every run", () => {
    expect([parseFilter("")(run()), parseFilter("   ")(run())]).toEqual([true, true]);
  });

  test("key=value and key:value match params; numbers compare by value; spaces around = are fine", () => {
    const a = run({ run_id: "a" });
    const b = run({ run_id: "b", params: { lr: "0.0003" } });
    const c = run({ run_id: "c", params: { lr: "1e-3" } });
    expect(keep("lr=3e-4", [a, b, c])).toEqual(["a", "b"]);
    expect(keep("lr = 3e-4", [a, b, c])).toEqual(["a", "b"]);
    expect(keep("lr:1e-3", [a, b, c])).toEqual(["c"]);
    expect(keep("model:resnet*", [a, run({ run_id: "d", params: { model: "vit" } })])).toEqual(["a"]);
    expect(keep("seed_mode=x", [a])).toEqual([]);
  });

  test("tag:, status:, by: and != negation", () => {
    const a = run({ run_id: "a" });
    const q = run({ run_id: "q", status: "queued", tags: [], created_by: "human:sam" });
    expect(keep("tag:final", [a, q])).toEqual(["a"]);
    expect(keep("tag:fin*", [a, q])).toEqual(["a"]);
    expect(keep("status:queued", [a, q])).toEqual(["q"]);
    expect(keep("status!=queued", [a, q])).toEqual(["a"]);
    expect(keep("by:agent", [a, q])).toEqual(["a"]);
    expect(keep("by:sam", [a, q])).toEqual(["q"]);
    expect(keep("by:human:*", [a, q])).toEqual(["q"]);
  });

  test("bare words match the display name or the derived name, case-insensitively, or a run id prefix", () => {
    const a = run({ run_id: "a1" });
    const r = run({ run_id: "b2", name: "Long warmup", derived_name: "lr 1e-3", renamed: true });
    expect(keep("BEAM", [a, r])).toEqual(["a1"]);
    expect(keep("warmup", [a, r])).toEqual(["b2"]);
    expect(keep("1e-3", [a, r])).toEqual(["b2"]);
    expect(keep("b2", [a, r])).toEqual(["b2"]);
    expect(keep("name:long*", [a, r])).toEqual(["b2"]);
  });

  test("every token must hold", () => {
    const a = run({ run_id: "a" });
    const b = run({ run_id: "b", status: "running" });
    expect(keep("tag:final status:running", [a, b])).toEqual(["b"]);
  });
});

test("tokenize glues key = value and splits on whitespace", () => {
  expect(tokenize("  lr = 3e-4   tag: final status != queued beam ")).toEqual(["lr=3e-4", "tag:final", "status!=queued", "beam"]);
});

test("globMatch: * is any run of characters, the rest is literal, case-insensitive", () => {
  expect([globMatch("res*", "ResNet50"), globMatch("a.b", "axb"), globMatch("*", ""), globMatch("x", "xy")]).toEqual([
    true, false, true, false,
  ]);
});
