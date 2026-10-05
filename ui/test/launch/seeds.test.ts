import { describe, expect, test } from "bun:test";

import { MAX_SEEDS, nextSeeds, parseSeeds } from "../../src/launch/seeds";

describe("parseSeeds", () => {
  test("reads integers separated by commas or spaces, in order", () => {
    expect(parseSeeds("4, 5, 6")).toEqual({ seeds: [4, 5, 6], error: null });
    expect(parseSeeds(" 9 1,2 ")).toEqual({ seeds: [9, 1, 2], error: null });
  });

  test("expands inclusive ranges and drops repeats", () => {
    expect(parseSeeds("1-3 7")).toEqual({ seeds: [1, 2, 3, 7], error: null });
    expect(parseSeeds("3, 3, 1-3")).toEqual({ seeds: [3, 1, 2], error: null });
  });

  test("names the first bad token", () => {
    expect(parseSeeds("")).toEqual({ seeds: [], error: "none" });
    expect(parseSeeds("4, x")).toEqual({ seeds: [], error: "bad seed x" });
    expect(parseSeeds("-1")).toEqual({ seeds: [], error: "bad seed -1" });
    expect(parseSeeds("5-2")).toEqual({ seeds: [], error: "bad range 5-2" });
    expect(parseSeeds("2147483648")).toEqual({ seeds: [], error: "seed too large: 2147483648" });
  });

  test(`allows at most ${MAX_SEEDS} seeds`, () => {
    expect(parseSeeds("0-63").seeds).toHaveLength(64);
    expect(parseSeeds("0-63 64").error).toBe("at most 64 seeds");
    expect(parseSeeds("1-1000000000").error).toBe("at most 64 seeds");
  });
});

describe("nextSeeds", () => {
  test("never proposes out-of-range or reused seeds at the upper boundary", () => {
    expect(nextSeeds([2147483645])).toEqual([2147483646, 2147483647]);
    expect(nextSeeds([2147483647])).toEqual([]);
    expect(parseSeeds(nextSeeds([2147483646]).join(",")).error).toBeNull();
  });

  test("handles large histories without spreading them into function arguments", () => {
    expect(nextSeeds(Array.from({ length: 200_000 }, (_, i) => i))).toEqual([200_000, 200_001, 200_002]);
  });

  test("continues after the largest seed used", () => {
    expect(nextSeeds([1, 2, 3, null])).toEqual([4, 5, 6]);
    expect(nextSeeds([9], 2)).toEqual([10, 11]);
  });

  test("starts at 1 when no seed was used", () => {
    expect(nextSeeds([])).toEqual([1, 2, 3]);
    expect(nextSeeds([null])).toEqual([1, 2, 3]);
  });
});
