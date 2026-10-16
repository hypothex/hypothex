import { describe, expect, test } from "bun:test";
import { fmtClock, fmtClockTip, fmtSpan, localOffset, timeTicks } from "../../src/charts/timeAxis";

describe("timeTicks", () => {
  test("whole time units: 15 s, 30 min, days", () => {
    expect(timeTicks(0, 45, 4)).toEqual([0, 15, 30, 45]);
    expect(timeTicks(0, 5400, 4)).toEqual([0, 1800, 3600, 5400]);
    expect(timeTicks(100, 3700, 4)).toEqual([900, 1800, 2700, 3600]);
    expect(timeTicks(0, 10 * 86400, 4).every((v) => v % 86400 === 0)).toBe(true);
  });

  test("the offset aligns ticks to local hours (UTC+5:30)", () => {
    const off = 19800;
    const ticks = timeTicks(1_792_150_000, 1_792_150_000 + 4 * 3600, 4, off);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    for (const v of ticks) expect((v + off) % 3600).toBe(0);
  });

  test("a span across a DST change keeps every tick on a whole local hour", () => {
    const change = 1_792_000_000; // local time jumps from UTC+1 to UTC+2 here
    const off = (t: number): number => (t < change ? 3600 : 7200);
    const ticks = timeTicks(change - 3 * 3600 - 600, change + 3 * 3600, 4, off);
    expect(ticks.some((v) => v < change) && ticks.some((v) => v >= change)).toBe(true);
    for (const v of ticks) expect((v + off(v)) % 3600).toBe(0);
    expect(new Set(ticks).size).toBe(ticks.length);
    // the clock back (UTC+2 to UTC+1): a repeated local hour gives no duplicate tick
    const back = (t: number): number => (t < change ? 7200 : 3600);
    const again = timeTicks(change - 4 * 3600, change + 4 * 3600, 6, back);
    for (const v of again) expect((v + back(v)) % 3600).toBe(0);
    expect([...again].sort((x, y) => x - y)).toEqual(again);
  });

  test("sub-second spans at epoch seconds keep decimal steps; empty spans give one tick", () => {
    const t = 1_792_152_689;
    const ticks = timeTicks(t + 0.1, t + 0.9, 4);
    expect(ticks.map((v) => +(v - t).toFixed(6))).toEqual([0.25, 0.5, 0.75]);
    expect(timeTicks(5, 5, 4)).toEqual([5]);
    expect(timeTicks(Number.NaN, 1, 4)).toEqual([]);
  });
});

describe("formats", () => {
  const T = 1_792_152_689;
  const d = new Date(T * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;

  test("fmtClock: as precise as the tick step", () => {
    expect(fmtClock(T, 600)).toBe(hm);
    expect(fmtClock(T, 15)).toBe(`${hm}:${p(d.getSeconds())}`);
    expect(fmtClock(T + 0.25, 0.05)).toBe(`${hm}:${p(d.getSeconds())}.25`);
    expect(fmtClock(T, 86400)).toBe(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
    expect(fmtClockTip(T, 600)).toBe(`${hm}:${p(d.getSeconds())}`);
  });

  test("fmtSpan: largest whole unit, up to 2 decimals", () => {
    expect([0, 0.0005, 0.25, 30, 90, 120, 3600, 5400, 4500].map(fmtSpan)).toEqual([
      "0", "0.5ms", "250ms", "30s", "1.5m", "2m", "1h", "1.5h", "1.25h",
    ]);
    expect(fmtSpan(-90)).toBe("−1.5m");
  });

  test("localOffset is the negated timezone offset in seconds", () => {
    expect(localOffset(T)).toBe(-d.getTimezoneOffset() * 60);
  });
});
