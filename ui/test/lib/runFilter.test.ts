import { describe, expect, test } from "bun:test";
import type { TaskRun } from "../../src/api/models";
import { parseSelection } from "../../src/task/useRunSelection";
import { MAX_FILTER, compileGlob, globMatch, parseFilter, tokenize } from "../../src/lib/runFilter";

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

describe("compileGlob", () => {
  test("anchors the first and last segment and scans the middle in order", () => {
    const m = (p: string, v: string) => compileGlob(p)(v);
    expect([m("a*b*c", "aXbYc"), m("a*b*c", "acb"), m("a*c", "ac"), m("ab*ba", "aba"), m("*mid*", "a mid b")]).toEqual([
      true, false, true, false, true,
    ]);
    expect([m("**", "x"), m("x**", "x"), m("*x", "yx"), m("x*", "xy"), m("RES*", "resnet"), m("a*", "A\nb")]).toEqual([
      true, true, true, true, true, true,
    ]);
    expect([m("", ""), m("", "x"), m("a?b", "axb"), m("a.b", "a.b"), m("[x]", "[x]")]).toEqual([true, false, false, true, true]);
  });

  test("a pathological pattern stays fast (no backtracking)", () => {
    const pattern = `${"a*".repeat(50)}b`;
    const value = "a".repeat(10_000);
    const t0 = performance.now();
    expect(globMatch(pattern, value)).toBe(false);
    expect(compileGlob(`${"a*".repeat(50)}a`)(value)).toBe(true);
    expect(compileGlob(`*${"a*".repeat(50)}c*`)(value)).toBe(false);
    expect(performance.now() - t0).toBeLessThan(50);
  });

  test("parseFilter never builds a RegExp from the filter text", () => {
    const Original = globalThis.RegExp;
    let built = 0;
    globalThis.RegExp = new Proxy(Original, {
      construct(target, args) {
        built += 1;
        return Reflect.construct(target, args);
      },
      apply(target, self, args) {
        built += 1;
        return Reflect.apply(target, self, args);
      },
    });
    try {
      const pred = parseFilter("model:res* tag:fin* status:fin* by:agent* name:lr* lr=3e-4 beam");
      expect(keep("model:res* tag:fin*", [run({ run_id: "a" })])).toEqual(["a"]);
      pred(run());
    } finally {
      globalThis.RegExp = Original;
    }
    expect(built).toBe(0);
  });
});

describe("tokenize stays linear", () => {
  test("100k spaces then x tokenizes and parses in < 50 ms", () => {
    const text = `${" ".repeat(100_000)}x`;
    const t0 = performance.now();
    expect(tokenize(text)).toEqual(["x"]);
    parseFilter(text);
    expect(performance.now() - t0).toBeLessThan(50);
  });

  test("operators glue to their neighbours across any whitespace, as before", () => {
    expect(tokenize("lr   =   3e-4")).toEqual(["lr=3e-4"]);
    expect(tokenize("lr= 3e-4 tag :final a : b : c")).toEqual(["lr=3e-4", "tag:final", "a:b:c"]);
    expect(tokenize("status !=  queued")).toEqual(["status!=queued"]);
    expect(tokenize("= x")).toEqual(["=x"]);
    expect(tokenize("lr =")).toEqual(["lr="]);
    expect(tokenize("a ! = b")).toEqual(["a", "!=b"]);
    expect(tokenize("\tlr\n=\n1  beam")).toEqual(["lr=1", "beam"]);
  });

  test(`a filter longer than ${MAX_FILTER} characters is cut`, () => {
    expect(MAX_FILTER).toBe(512);
    const long = `${"a".repeat(MAX_FILTER)} tag:never`;
    // the cut drops the tag token, so every run passes the remaining word test only
    expect(parseFilter(long)(run({ name: "a".repeat(MAX_FILTER) }))).toBe(true);
  });
});

test("a shared ?filter= link is cut to MAX_FILTER characters", () => {
  const sel = parseSelection(new URLSearchParams({ filter: " ".repeat(200_000) }), { sortDir: "desc" });
  expect(sel.filter.length).toBe(MAX_FILTER);
});
