import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import {
  DistributionPanel,
  fmtTick,
  logTicks,
  niceLogDomain,
  seriesColor,
  signedPct,
  signedPctNum,
  xAxis,
  xScale,
} from "../../src/panels/Distribution";

afterEach(cleanup);

const ROWS = [
  {
    group_id: "g1",
    label: "baseline",
    n: 4,
    p50: 20,
    p95: 80,
    p99: 200,
    ecdf: [
      [10, 0.25],
      [20, 0.5],
      [80, 0.75],
      [200, 1],
    ],
    seeds: [
      { run_id: "r1", p50: 19, p95: 78, p99: 190 },
      { run_id: "r2", p50: 21, p95: 82, p99: 210 },
    ],
  },
  {
    group_id: "g2",
    label: "cache",
    n: 4,
    p50: 12,
    p95: 40,
    p99: 90,
    ecdf: [
      [8, 0.25],
      [12, 0.5],
      [40, 0.75],
      [90, 1],
    ],
    seeds: [{ run_id: "r3", p50: 12, p95: 41, p99: 88 }],
  },
];

const dist = (meta: Record<string, unknown>, rows: unknown[] = ROWS): PanelResult => ({
  type: "distribution",
  title: "Latency",
  rows: rows as Record<string, unknown>[],
  meta,
});

const tickLabels = (c: HTMLElement) =>
  [...c.querySelectorAll("text[data-tick]")].map((t) => t.getAttribute("data-tick"));

describe("log axis helpers", () => {
  test("niceLogDomain widens to 1-2-5 values", () => {
    expect(niceLogDomain(7.3, 812)).toEqual([5, 1000]);
    expect(niceLogDomain(5, 1000)).toEqual([5, 1000]);
    expect(niceLogDomain(0.008, 2.2)).toEqual([0.005, 5]);
    expect(niceLogDomain(100, 100)).toEqual([100, 1000]);
  });

  test("logTicks lists 1-2-5 values inside the domain", () => {
    expect(logTicks(5, 1000)).toEqual([5, 10, 20, 50, 100, 200, 500, 1000]);
    expect(logTicks(0.005, 5)).toEqual([0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5]);
  });

  test("xAxis keeps only powers of ten when there are more than 8 ticks", () => {
    expect(xAxis("log", [0.008, 2.2]).ticks).toEqual([0.01, 0.1, 1]);
    expect(xAxis("log", [-1, 0, 7.3, 812])).toEqual({
      domain: [5, 1000],
      ticks: [5, 10, 20, 50, 100, 200, 500, 1000],
    });
  });

  test("xAxis linear starts at zero and uses nice ticks", () => {
    // d3-scale: [0, 210].nice(6) -> [0, 250]; ticks(6) step 50
    expect(xAxis("linear", [8, 210])).toEqual({
      domain: [0, 250],
      ticks: [0, 50, 100, 150, 200, 250],
    });
  });

  test("xScale log puts the geometric midpoint in the middle and clamps", () => {
    const x = xScale("log", [10, 1000], [0, 200]);
    expect(x(100)).toBeCloseTo(100, 6);
    expect(x(1)).toBeCloseTo(0, 6);
    expect(xScale("linear", [0, 100], [0, 200])(50)).toBe(100);
  });

  test("fmtTick is short", () => {
    expect(fmtTick(0.05)).toBe("0.05");
    expect(fmtTick(20)).toBe("20");
    expect(fmtTick(1000)).toBe("1,000");
  });
});

describe("signed percents", () => {
  test("U+2212 minus, explicit plus, fixed decimals", () => {
    expect(signedPct(-0.3)).toBe("−30%");
    expect(signedPct(0)).toBe("+0%");
    expect(signedPctNum(0.041, 1)).toBe("+4.1");
    expect(signedPctNum(-0.452)).toBe("−45");
  });
});

describe("seriesColor", () => {
  test("fixed order with light and dark steps, then muted ink", () => {
    expect(seriesColor(0)).toBe("light-dark(#2a78d6, #4a90e8)");
    expect(seriesColor(1)).toBe("light-dark(#e0602e, #e06a35)");
    expect(seriesColor(5)).toBe("var(--ink-3)");
  });
});

describe("DistributionPanel", () => {
  test("draws one ECDF per group with labels, ticks and seed dots", () => {
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" })} />);
    expect(container.querySelectorAll('[data-testid="ecdf"]').length).toBe(2);
    expect(screen.getByText("baseline")).toBeTruthy();
    expect(screen.getByText("cache")).toBeTruthy();
    expect(container.querySelectorAll("[data-q]").length).toBe(6);
    expect(container.querySelectorAll("[data-seed]").length).toBe(3);
    expect(screen.getByText("ms, log")).toBeTruthy();
  });

  test("log axis: domain [5, 500], ticks at 1-2-5, positions on a log scale", () => {
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" })} />);
    expect(tickLabels(container)).toEqual(["5", "10", "20", "50", "100", "200", "500"]);
    // x range [132, 704]; 50 is the geometric middle of [5, 500]
    const t50 = container.querySelector('text[data-tick="50"]');
    expect(Number(t50?.getAttribute("x"))).toBeCloseTo(418, 3);
    const g1 = container.querySelector('[data-group="g1"]') as Element;
    const x = (q: string) => Number(g1.querySelector(`[data-q="${q}"]`)?.getAttribute("x1"));
    // 132 + log10(80 / 5) / log10(100) * 572
    expect(x("p95")).toBeCloseTo(476.378, 2);
    expect(x("p50")).toBeLessThan(x("p95"));
    expect(x("p95")).toBeLessThan(x("p99"));
  });

  test("tick and seed tooltips carry the value and unit", () => {
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" })} />);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain("baseline p95 80 ms\nn = 4, 2 seeds");
    expect(titles).toContain("r2\np50 21 ms, p95 82 ms, p99 210 ms");
  });

  test("linear scale when asked", () => {
    const { container } = render(
      <DistributionPanel result={dist({ scale: "linear", unit: "ms" })} />,
    );
    expect(tickLabels(container)).toEqual(["0", "50", "100", "150", "200", "250"]);
    const t100 = container.querySelector('text[data-tick="100"]');
    expect(Number(t100?.getAttribute("x"))).toBeCloseTo(360.8, 3);
    expect(screen.getByText("ms")).toBeTruthy();
  });

  test("one sample and a zero latency still draw finite geometry", () => {
    const one = [
      {
        group_id: "g1",
        label: "tiny",
        n: 2,
        p50: 0,
        p95: 100,
        p99: 100,
        ecdf: [
          [0, 0.5],
          [100, 1],
        ],
        seeds: [],
      },
    ];
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" }, one)} />);
    expect(container.innerHTML).not.toContain("NaN");
    expect(container.querySelectorAll('[data-testid="ecdf"]').length).toBe(1);
    // zero is dropped from the log domain and its tick clamps to the left edge
    const p50 = container.querySelector('[data-q="p50"]');
    expect(Number(p50?.getAttribute("x1"))).toBe(132);
  });

  test("the backend's meta names the axis with the sample name", () => {
    render(<DistributionPanel result={dist({ name: "latency_ms", scale: "log" })} />);
    expect(screen.getByText("latency_ms, log")).toBeTruthy();
  });

  test("empty result says so", () => {
    render(<DistributionPanel result={dist({}, [])} />);
    expect(screen.getByText("No samples")).toBeTruthy();
  });
});

describe("DistributionPanel as a percentile table", () => {
  // g1 is the baseline; g2 has one repeat on p95's comparison, so no interval there
  const DELTA_ROWS = [
    { ...ROWS[0], vs_baseline: null },
    {
      ...ROWS[1],
      vs_baseline: {
        p50: [-0.4, -0.452, -0.348],
        p95: [-0.5, null, null],
        p99: [-0.55, -0.6, -0.5],
      },
    },
  ];
  const cell = (c: HTMLElement, g: string, q: string) =>
    c.querySelector(`tr[data-group="${g}"] td[data-q="${q}"]`) as HTMLElement;

  test("values, Δ% with its CI, and ref on the baseline row", () => {
    const { container } = render(
      <DistributionPanel
        result={dist({ render: "table", unit: "ms", baseline: "g1" }, DELTA_ROWS)}
      />,
    );
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelectorAll('[data-testid="ptable"] tbody tr').length).toBe(2);
    expect(screen.getByText("p95 ms")).toBeTruthy();
    expect(cell(container, "g1", "p50").textContent).toBe("20ref");
    expect(cell(container, "g2", "p50").textContent).toBe("12−40% [−45, −35]");
    expect(cell(container, "g2", "p95").textContent).toBe("40−50%");
    expect(cell(container, "g2", "p99").textContent).toBe("90−55% [−60, −50]");
    expect(cell(container, "g2", "p50").getAttribute("title")).toBe(
      "cache p50: repeats 12\nvs baseline −40.0%, 95% CI −45.2 to −34.8%",
    );
    expect(cell(container, "g2", "p95").getAttribute("title")).toBe(
      "cache p95: repeats 41\nvs baseline −50.0%, one repeat: no CI",
    );
    expect(cell(container, "g1", "p95").getAttribute("title")).toBe(
      "baseline p95: repeats 78, 82\nbaseline",
    );
  });

  test("without a baseline the table shows values only", () => {
    const { container } = render(<DistributionPanel result={dist({ render: "table" })} />);
    expect(container.querySelectorAll("[data-delta]").length).toBe(0);
    expect(cell(container, "g1", "p99").textContent).toBe("200");
    expect(cell(container, "g2", "p50").getAttribute("title")).toBe("cache p50: repeats 12");
  });
});

test("the ECDF 'share' title sits above the top tick label, not on it", () => {
  const { container } = render(<DistributionPanel result={dist({})} />);
  const share = container.querySelector("[data-testid='share']");
  const one = [...container.querySelectorAll("text")].find((t) => t.textContent === "1");
  // tick labels are 11 px: the "1" occupies [baseline - 11, baseline]
  const shareBase = Number(share?.getAttribute("y"));
  const oneTop = Number(one?.getAttribute("y")) - 11;
  expect(shareBase + 3).toBeLessThanOrEqual(oneTop);
});
