import { describe, expect, test } from "bun:test";
import {
  displayPath,
  firstClause,
  fmtBytes,
  fmtClock,
  fmtCount,
  fmtDate,
  fmtDelta,
  fmtDuration,
  fmtInterval,
  fmtP,
  fmtScore,
  fmtScoreUnit,
  fmtSigned,
  fmtTime,
  fmtUsd,
  fmtValue,
  isAgent,
  primaryMetricName,
  relativeTo,
  runSeconds,
  shellJoin,
  shortHash,
  shortId,
  splitHostPath,
  tailPath,
} from "../../src/pages/components/format";
import { makeRecord } from "./fixtures";

describe("numbers", () => {
  test("fmtScoreUnit adds the unit: 3 significant digits, cents for small dollars", () => {
    expect(fmtScoreUnit(165.62, "ms")).toBe("166 ms");
    expect(fmtScoreUnit(0.5512, "$")).toBe("$0.55");
    expect(fmtScoreUnit(332.4, "$")).toBe("$332");
    expect(fmtScoreUnit(0.25, "s")).toBe("0.25 s");
    expect(fmtScoreUnit(15300, "tokens")).toBe("15.3k tokens");
    expect(fmtScoreUnit(0.9222, "")).toBe("0.9222");
    expect(fmtScoreUnit(null, "ms")).toBe("—");
  });

  test("fmtScore uses 4 decimals in [-1, 1], 3 significant digits above, SI above 1000", () => {
    expect(fmtScore(0.9222222222222222)).toBe("0.9222");
    expect(fmtScore(1)).toBe("1.0000");
    expect(fmtScore(-0.25)).toBe("−0.2500");
    expect(fmtScore(68.4)).toBe("68.4");
    expect(fmtScore(166.4)).toBe("166");
    expect(fmtScore(153000)).toBe("153k");
    expect(fmtScore(null)).toBe("—");
    expect(fmtScore(Number.NaN)).toBe("—");
  });

  test("fmtDelta and fmtSigned always carry a sign", () => {
    expect(fmtDelta(6 / 180)).toBe("+0.0333");
    expect(fmtDelta(-0.037)).toBe("−0.0370");
    expect(fmtDelta(0)).toBe("0.0000");
    expect(fmtSigned(6)).toBe("+6");
    expect(fmtSigned(-2)).toBe("−2");
    expect(fmtSigned(0)).toBe("0");
  });

  test("fmtInterval uses 3 decimals for fractions", () => {
    expect(fmtInterval(0.874, 0.953)).toBe("0.874–0.953");
    expect(fmtInterval(164.2, 168.1)).toBe("164–168");
  });

  test("fmtP: two decimals, three below 0.01, floor at 0.001", () => {
    // 598/4096 is the exact two-sided sign-test p for 9 fixed vs 3 broken
    expect(fmtP(598 / 4096)).toBe("p = 0.15");
    expect(fmtP(2 / 1024)).toBe("p = 0.002");
    expect(fmtP(0.0004)).toBe("p < 0.001");
    expect(fmtP(null)).toBe("—");
  });

  test("fmtBytes, fmtUsd, fmtCount", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(18494)).toBe("18.5 KB");
    expect(fmtBytes(26123)).toBe("26.1 KB");
    expect(fmtBytes(1_200_000)).toBe("1.2 MB");
    expect(fmtBytes(5.4e9)).toBe("5.4 GB");
    expect(fmtUsd(0.097)).toBe("$0.097");
    expect(fmtUsd(0.25)).toBe("$0.25");
    expect(fmtUsd(12.4)).toBe("$12.40");
    expect(fmtCount(13)).toBe("13");
    expect(fmtCount(4500)).toBe("4.5k");
    expect(fmtCount(153000)).toBe("153k");
  });
});

describe("time", () => {
  test("durations", () => {
    expect(fmtDuration(0.822124)).toBe("0.8 s");
    expect(fmtDuration(125)).toBe("2m 5s");
    expect(fmtDuration(20400)).toBe("5h 40m");
    expect(fmtDuration(null)).toBe("—");
  });

  test("runSeconds uses ended_at, or now while running", () => {
    // parseTime keeps milliseconds: 07.578 - 06.756 = 0.822 s
    expect(runSeconds(makeRecord())).toBeCloseTo(0.822, 6);
    const running = makeRecord({ ended_at: null, started_at: "2026-09-26T21:00:00Z" });
    expect(runSeconds(running, Date.parse("2026-09-26T21:00:30Z"))).toBe(30);
    expect(runSeconds(makeRecord({ started_at: null }))).toBeNull();
  });

  test("clock formats are UTC and accept microseconds and offsets", () => {
    expect(fmtClock("2026-09-26T21:03:06.685638Z")).toBe("21:03");
    expect(fmtTime("2026-09-26T21:03:06.685638Z")).toBe("21:03:06 UTC");
    expect(fmtDate("2026-09-26T21:03:56.036288+00:00")).toBe("2026-09-26 21:03");
    expect(fmtClock("not a time")).toBe("—");
  });
});

describe("text and paths", () => {
  test("shortId and shortHash", () => {
    expect(shortId("20260926-210306-toy-test-6f71")).toBe("6f71");
    expect(shortHash("sha256:e662a37bb8a556fd")).toBe("e662a37b");
  });

  test("firstClause cuts at the first clause break", () => {
    expect(firstClause("RBF-kernel SVM should beat RF because clusters are round", "x")).toBe(
      "RBF-kernel SVM",
    );
    expect(firstClause("baseline rf", "x")).toBe("baseline rf");
    expect(firstClause("lr 0.5 warmup, then decay", "x")).toBe("lr 0.5 warmup");
    expect(firstClause("  ", "run 6f71")).toBe("run 6f71");
    expect(firstClause("a".repeat(50), "x")).toBe(`${"a".repeat(39)}…`);
  });

  test("splitHostPath and displayPath", () => {
    expect(splitHostPath("local:/x/y")).toEqual({ host: "local", path: "/x/y" });
    expect(splitHostPath("/x/y")).toEqual({ host: "local", path: "/x/y" });
    expect(splitHostPath("gpu-a03:/scratch/run")).toEqual({ host: "gpu-a03", path: "/scratch/run" });
    expect(displayPath("local", "/x")).toBe("/x");
    expect(displayPath("gpu-a03", "/x")).toBe("gpu-a03:/x");
  });

  test("relativeTo and tailPath", () => {
    expect(relativeTo("/r/run1/logs/stdout.log", "/r/run1")).toBe("logs/stdout.log");
    expect(relativeTo("/r/run1/logs", "/r/run1/")).toBe("logs");
    expect(relativeTo("/r/run1", "/r/run1")).toBe(".");
    expect(relativeTo("/r/run10/x", "/r/run1")).toBeNull();
    expect(tailPath("/a/b/c/d/e")).toBe("…/c/d/e");
    expect(tailPath("/a/b")).toBe("/a/b");
  });

  test("shellJoin quotes only when needed", () => {
    expect(shellJoin(["python", "train.py", "--seed={seed}", "--name", "a b"])).toBe(
      "python train.py --seed={seed} --name 'a b'",
    );
    expect(shellJoin(["echo", "it's", ""])).toBe(`echo 'it'"'"'s' ''`);
  });

  test("fmtValue, primaryMetricName, isAgent", () => {
    expect(fmtValue("x")).toBe("x");
    expect(fmtValue(2)).toBe("2");
    expect(fmtValue(false)).toBe("false");
    expect(fmtValue(null)).toBe("—");
    expect(fmtValue({ a: 1 })).toBe('{"a":1}');
    expect(fmtValue("y".repeat(100))).toBe(`${"y".repeat(79)}…`);
    expect(primaryMetricName("accuracy/value")).toBe("accuracy");
    expect(isAgent("agent:acceptance")).toBe(true);
    expect(isAgent("human")).toBe(false);
  });
});
