import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import {
  bestIndex,
  refLabel,
  paretoPath,
  type ScatterMeta,
  type ScatterRow,
  ScatterPanel,
  yDirOf,
} from "../../src/panels/Scatter";

afterEach(cleanup);

const ROWS: ScatterRow[] = [
  {
    group_id: "g1",
    label: "mcts-64",
    x: 0.3,
    x_lo: 0.28,
    x_hi: 0.32,
    y: 0.6,
    y_lo: 0.53,
    y_hi: 0.67,
    seeds: [
      { x: 0.29, y: 0.59 },
      { x: 0.31, y: 0.61 },
    ],
    pareto: true,
    regression: false,
  },
  {
    group_id: "g2",
    label: "greedy",
    x: 0.05,
    x_lo: null,
    x_hi: null,
    y: 0.4,
    y_lo: 0.33,
    y_hi: 0.47,
    seeds: [{ x: 0.05, y: 0.4 }],
    pareto: true,
    regression: false,
  },
  {
    group_id: "g3",
    label: "beam",
    x: 0.5,
    x_lo: 0.45,
    x_hi: 0.55,
    y: 0.5,
    y_lo: 0.43,
    y_hi: 0.57,
    seeds: [],
    pareto: false,
    regression: false,
  },
];

// `object` so a typed `ScatterMeta` (no index signature) and ad hoc metas both fit
const scatter = (meta: object, rows: ScatterRow[] = ROWS): PanelResult => ({
  type: "scatter",
  title: "Cost vs solved",
  rows: rows as unknown as Record<string, unknown>[],
  meta: meta as Record<string, unknown>,
});

const META = { x_label: "$ / attempt", y_label: "solved@v2", pareto: { x: "min", y: "max" } };

const mean = (c: HTMLElement, g: string) =>
  c.querySelector(`[data-group="${g}"] [data-testid="mean"]`) as SVGElement;

describe("paretoPath", () => {
  test("lower x better: across, then up, then tail to the right edge", () => {
    const front = [
      { x: 0.3, y: 0.6 },
      { x: 0.05, y: 0.4 },
      { x: 1.2, y: 0.66 },
    ];
    expect(paretoPath(front, "min", 2)).toEqual([
      [0.05, 0.4],
      [0.3, 0.4],
      [0.3, 0.6],
      [1.2, 0.6],
      [1.2, 0.66],
      [2, 0.66],
    ]);
  });

  test("higher x better: down first, tail to the left edge", () => {
    expect(
      paretoPath(
        [
          { x: 1, y: 5 },
          { x: 3, y: 2 },
        ],
        "max",
        0,
      ),
    ).toEqual([
      [0, 5],
      [1, 5],
      [1, 2],
      [3, 2],
    ]);
  });

  test("empty front gives no path", () => {
    expect(paretoPath([], "min", 1)).toEqual([]);
  });
});

describe("bestIndex", () => {
  test("highest y, lowest y, or the named group", () => {
    expect(bestIndex(ROWS, "max")).toBe(0);
    expect(bestIndex(ROWS, "min")).toBe(1);
    expect(bestIndex(ROWS, "max", "g3")).toBe(2);
    expect(bestIndex(ROWS, "max", null)).toBe(-1); // the server found no best group
    expect(bestIndex([], "max")).toBe(-1);
  });
});

describe("yDirOf", () => {
  test("the metric's direction wins over the Pareto settings", () => {
    expect(yDirOf({ y_higher_is_better: false, pareto: { x: "min", y: "max" } })).toBe("min");
    expect(yDirOf({ y_higher_is_better: true, pareto: { x: "min", y: "min" } })).toBe("max");
    expect(yDirOf({ pareto: { x: "min", y: "min" } })).toBe("min");
    expect(yDirOf({ pareto: null })).toBe("max");
    expect(yDirOf({})).toBe("max");
  });
});

describe("ScatterPanel", () => {
  test("one mean per group; best, front and dominated styles differ", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    expect(container.querySelectorAll('[data-testid="mean"]').length).toBe(3);
    expect(mean(container, "g1").dataset.best).toBe("true");
    expect(mean(container, "g1").style.fill).toBe("var(--best)");
    expect(mean(container, "g2").style.fill).toBe("var(--ink)");
    expect(mean(container, "g3").dataset.pareto).toBe("false");
    expect(mean(container, "g3").style.fill).toBe("var(--paper)");
    expect(container.querySelectorAll('[data-testid="regression"]').length).toBe(0);
  });

  test("seed dots, whiskers only where intervals exist, labels", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    expect(container.querySelectorAll("[data-seed]").length).toBe(3);
    expect(container.querySelectorAll('[data-testid="ywhisk"]').length).toBe(3);
    expect(container.querySelectorAll('[data-testid="xwhisk"]').length).toBe(2);
    for (const l of ["mcts-64", "greedy", "beam", "$ / attempt", "solved@v2"]) {
      expect(screen.getByText(l)).toBeTruthy();
    }
  });

  test("Pareto staircase runs through front groups only, plus a tail", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    const d = container.querySelector('[data-testid="pareto"]')?.getAttribute("d") ?? "";
    // vertices: greedy, across to x=0.3, up to mcts-64, tail to the right edge
    // x domain [0, 0.6] -> [52, 624]; y domain [0.3, 0.7] -> [316, 26]
    // greedy (0.05, 0.4) -> (52 + 0.05 / 0.6 * 572, 316 - 0.1 / 0.4 * 290) = (99.7, 243.5)
    // across to mcts-64 x = 0.3 -> 338, up to y = 0.6 -> 98.5, tail to the right edge 624
    expect(d).toBe("M99.7 243.5L338.0 243.5L338.0 98.5L624.0 98.5");
  });

  test("tooltip names values, intervals and front membership", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain(
      "beam\nsolved@v2 0.500 [0.430, 0.570]\n$ / attempt 0.500 [0.450, 0.550]\n0 seeds, dominated",
    );
  });

  test("log x axis uses 1-2-5 ticks", () => {
    const { container } = render(<ScatterPanel result={scatter({ ...META, scale: "log" })} />);
    const ticks = [...container.querySelectorAll("text[data-tick]")].map((t) =>
      t.getAttribute("data-tick"),
    );
    // values span 0.05..0.55 -> domain [0.05, 1]
    expect(ticks).toEqual(["0.05", "0.1", "0.2", "0.5", "1"]);
    expect(screen.getByText("$ / attempt, log")).toBeTruthy();
  });

  test("a single group with no intervals still draws finite geometry", () => {
    const one: ScatterRow = {
      group_id: "g1",
      label: "only",
      x: 0,
      x_lo: null,
      x_hi: null,
      y: 0.5,
      y_lo: null,
      y_hi: null,
      seeds: [],
      pareto: true,
      regression: false,
    };
    for (const scale of ["linear", "log"]) {
      const { container, unmount } = render(<ScatterPanel result={scatter({ scale }, [one])} />);
      expect(container.innerHTML).not.toContain("NaN");
      expect(container.querySelectorAll('[data-testid="mean"]').length).toBe(1);
      unmount();
    }
  });

  test("the backend's meta names the axes and tooltips with short metric names", () => {
    const backend: ScatterMeta = {
      x: "usage.usd",
      y: "solved@v2/value",
      x_type: "quantitative",
      scale: "linear",
      pareto: { x: "min", y: "max" },
      y_higher_is_better: true,
      best_group: "g1",
    };
    const { container } = render(<ScatterPanel result={scatter(backend)} />);
    expect(screen.getByText("cost")).toBeTruthy();
    expect(screen.getByText("solved@v2")).toBeTruthy();
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain(
      "beam\nsolved@v2 0.500 [0.430, 0.570]\ncost 0.500 [0.450, 0.550]\n0 seeds, dominated",
    );
    expect(mean(container, "g1").dataset.best).toBe("true");
  });

  test("lower-is-better y with no Pareto settings: the server's best group is lit", () => {
    // e.g. a loss against wall time: the lowest mean (greedy, 0.4) is best, and with no
    // `pareto` in the view every row arrives `pareto: false` without being "dominated"
    const loss: ScatterMeta = {
      x: "usage.seconds",
      y: "val/loss",
      x_type: "quantitative",
      scale: "linear",
      pareto: null,
      y_higher_is_better: false,
      best_group: "g2",
    };
    const rows = ROWS.map((r) => ({ ...r, pareto: false }));
    const { container } = render(<ScatterPanel result={scatter(loss, rows)} />);
    expect(mean(container, "g2").dataset.best).toBe("true");
    expect(mean(container, "g2").style.fill).toBe("var(--best)");
    expect(mean(container, "g1").dataset.best).toBe("false");
    expect(mean(container, "g1").style.fill).toBe("var(--ink)");
    expect(mean(container, "g3").style.fill).toBe("var(--ink)"); // not hollow
    expect(container.querySelector('[data-testid="pareto"]')).toBeNull();
    expect(screen.queryByText("Pareto")).toBeNull();
    expect(screen.queryByText("dominated")).toBeNull();
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain(
      "beam\nval loss 0.500 [0.430, 0.570]\ntime 0.500 [0.450, 0.550]\n0 seeds",
    );
  });

  test("y_higher_is_better beats pareto.y; a null best_group lights no group", () => {
    // Pareto says y max, but the metric is lower-is-better: without best_group the lowest mean wins
    const low = render(
      <ScatterPanel result={scatter({ ...META, y_higher_is_better: false })} />,
    );
    expect(mean(low.container, "g2").dataset.best).toBe("true");
    expect(mean(low.container, "g1").dataset.best).toBe("false");
    low.unmount();
    const none = render(
      <ScatterPanel result={scatter({ ...META, y_higher_is_better: true, best_group: null })} />,
    );
    expect(none.container.querySelectorAll('[data-best="true"]').length).toBe(0);
    expect(mean(none.container, "g1").style.fill).toBe("var(--ink)"); // front, not best
  });

  test("ordinal x: versions in order; a regression is drawn in the failure colour with ▼", () => {
    const version = (v: string, y: number, regression: boolean): ScatterRow => ({
      group_id: v,
      label: v,
      x: v,
      x_lo: null,
      x_hi: null,
      y,
      y_lo: y - 0.025,
      y_hi: y + 0.025,
      seeds: [
        { x: v, y: y - 0.01 },
        { x: v, y: y + 0.01 },
      ],
      pareto: false,
      regression,
    });
    // the backend's meta for the agent_iteration "Solved by version" panel
    const meta: ScatterMeta = {
      x: "version",
      y: "solved/value",
      x_type: "ordinal",
      scale: "linear",
      pareto: null,
      y_higher_is_better: true,
      best_group: "v2",
    };
    const rows = [version("v1", 0.5, false), version("v2", 0.7, false), version("v3", 0.6, true)];
    const { container } = render(<ScatterPanel result={scatter(meta, rows)} />);
    expect(container.innerHTML).not.toContain("NaN");
    const ticks = [...container.querySelectorAll("text[data-tick]")].map((t) =>
      t.getAttribute("data-tick"),
    );
    expect(ticks).toEqual(["v1", "v2", "v3"]);
    // three bands over [52, 624]: v2's centre is 52 + 1.5 * 572 / 3 = 338; its square starts at 333
    expect(Number(mean(container, "v2").getAttribute("x"))).toBeCloseTo(333, 6);
    expect(mean(container, "v2").style.fill).toBe("var(--best)");
    expect(mean(container, "v1").style.fill).toBe("var(--ink)"); // no hollow "dominated" style
    expect(mean(container, "v3").dataset.regression).toBe("true");
    expect(mean(container, "v3").style.fill).toBe("var(--fail)");
    const glyphs = container.querySelectorAll('[data-testid="regression"]');
    expect(glyphs.length).toBe(1);
    expect(glyphs[0].closest("[data-group]")?.getAttribute("data-group")).toBe("v3");
    expect(glyphs[0].querySelector("text")?.textContent).toBe("▼");
    expect(glyphs[0].querySelector("title")?.textContent).toBe(
      "regression vs best earlier version",
    );
    expect(container.querySelector('[data-testid="pareto"]')).toBeNull();
    expect(container.querySelectorAll('[data-testid="xwhisk"]').length).toBe(0);
    expect(container.querySelectorAll("[data-seed]").length).toBe(6);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain(
      "v3\nsolved 0.600 [0.575, 0.625]\nversion v3\n2 seeds, regression vs best earlier version",
    );
    expect(screen.getByText("regression")).toBeTruthy(); // key item
    expect(screen.queryByText("Pareto")).toBeNull();
  });

  test("refLabel shortens refs", () => {
    expect(refLabel("solved/value")).toBe("solved");
    expect(refLabel("latency/p95")).toBe("latency p95");
    expect(refLabel("usage.usd")).toBe("cost");
    expect(refLabel("usage.usd/solved")).toBe("cost per solved");
    expect(refLabel("usage.tokens_in")).toBe("tokens in");
    expect(refLabel("version")).toBe("version");
  });

  test("x_unit and y_unit: currency leads each tick and the tooltip value", () => {
    const meta: ScatterMeta = {
      x: "usage.usd",
      y: "usage.usd/solved",
      x_type: "quantitative",
      scale: "linear",
      pareto: null,
      y_higher_is_better: false,
      best_group: "g1",
      x_unit: "$",
      y_unit: "$",
    };
    const { container } = render(<ScatterPanel result={scatter(meta)} />);
    const ticks = [...container.querySelectorAll("text[data-tick]")].map((t) => t.textContent);
    expect(ticks.every((t) => t?.startsWith("$"))).toBe(true);
    expect(screen.getByText("cost per solved")).toBeTruthy();
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent ?? "");
    expect(titles.some((t) => t.includes("cost per solved $0.5") && t.includes("cost $0.5"))).toBe(true);
  });

  test("empty result says so", () => {
    render(<ScatterPanel result={scatter({}, [])} />);
    expect(screen.getByText("No data")).toBeTruthy();
  });
});
