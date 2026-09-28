import { describe, expect, test } from "bun:test";
import { MINUS } from "../../src/charts/Scale";
import {
  fmtSig3,
  isLatencyLike,
  parseFormat,
  valueFormatter,
  withUnit,
} from "../../src/charts/valueFormat";

describe("valueFormatter fallbacks (no value_format)", () => {
  test("scores in [-1, 1] without a unit keep 4 decimals and absolute deltas", () => {
    const f = valueFormatter({}, [0.922222, 0.885185], "accuracy/value");
    expect(f.value(0.922222)).toBe("0.9222");
    expect(f.bound(0.874)).toBe("0.874");
    expect(f.spread(0.006415)).toBe("0.0064");
    expect(f.delta(0.885185, 0.922222)).toBe(`${MINUS}0.037`);
  });

  test("values above 1 get 3 significant figures", () => {
    const f = valueFormatter(undefined, [165.6221, 233.2682], "latency/p95");
    expect(f.num(165.6221)).toBe("166");
    expect(f.spread(2.8011)).toBe("2.80");
    expect(f.bound(229.1)).toBe("229");
  });

  test("a unit forces 3 significant figures and is attached", () => {
    const f = valueFormatter({ unit: "ms" }, [0.42], "rtt");
    expect(f.value(0.4213)).toBe("0.421 ms");
    expect(valueFormatter({ unit: "$" }, [0.55]).value(0.5512)).toBe("$0.551");
  });

  test("latency deltas are relative percentages", () => {
    const f = valueFormatter({ unit: "ms" }, [165.62, 210.58], "latency/p95");
    expect(f.delta(210.58, 165.62)).toBe("+27%");
    expect(f.delta(233.27, 165.62)).toBe("+41%");
    expect(f.delta(160, 165.62)).toBe(`${MINUS}3.4%`);
    // latency-like by key alone
    expect(valueFormatter(undefined, [166], "latency/p95").delta(210.58, 165.62)).toBe("+27%");
  });

  test("other big metrics show a signed absolute delta with the unit", () => {
    const f = valueFormatter({ unit: "$" }, [3.2, 4.5], "cost");
    expect(f.delta(4.5, 3.2)).toBe("+$1.3");
    expect(f.delta(3.2, 4.5)).toBe(`${MINUS}$1.3`);
    expect(valueFormatter(undefined, [148, 145], "solved").delta(145, 148)).toBe(`${MINUS}3`);
  });
});

describe("value_format from meta", () => {
  test("a d3-format specifier wins over the fallbacks", () => {
    const f = valueFormatter({ value_format: ".1%" }, [0.5]);
    expect(f.value(0.4213)).toBe("42.1%");
    expect(f.spread(0.012)).toBe("1.2%");
  });

  test("an invalid specifier falls back", () => {
    expect(parseFormat("not a format")).toBeNull();
    expect(parseFormat(undefined)).toBeNull();
    expect(valueFormatter({ value_format: "zz" }, [0.5]).value(0.42131)).toBe("0.4213");
  });

  test("backend hint fraction keeps 4 decimals and absolute deltas", () => {
    const f = valueFormatter({ unit: "", value_format: "fraction" }, [0.7417], "solved/value");
    expect(f.value(0.74167)).toBe("0.7417");
    expect(f.spread(0.01609)).toBe("0.0161");
    expect(f.delta(0.725, 0.74167)).toBe(`${MINUS}0.017`);
  });

  test("backend hint number gives 3 significant figures and absolute deltas", () => {
    const f = valueFormatter({ unit: "tokens", value_format: "number" }, [1234], "usage.tokens");
    expect(f.value(1234.4)).toBe("1,230 tokens");
    expect(f.delta(1300, 1234)).toBe("+66 tokens");
  });

  test("backend hint percent_delta gives relative deltas whatever the key", () => {
    const f = valueFormatter({ unit: "ms", value_format: "percent_delta" }, [165.6], "p95");
    expect(f.value(165.62)).toBe("166 ms");
    expect(f.spread(2.801)).toBe("2.80");
    expect(f.delta(210.58, 165.62)).toBe("+27%");
  });

  test("format plus unit", () => {
    expect(valueFormatter({ value_format: ",.0f", unit: "ms" }, [1234]).value(1234.4)).toBe("1,234 ms");
  });
});

test("helpers", () => {
  expect(withUnit("12", "%")).toBe("12%");
  expect(withUnit(`${MINUS}3`, "$")).toBe(`${MINUS}$3`);
  expect(withUnit("12", "")).toBe("12");
  expect(fmtSig3(0)).toBe("0");
  expect(fmtSig3(-1234.5)).toBe(`${MINUS}1,230`);
  expect(isLatencyLike("ms")).toBe(true);
  expect(isLatencyLike("", "train/loss")).toBe(false);
  expect(isLatencyLike("", "wall_time")).toBe(true);
});
