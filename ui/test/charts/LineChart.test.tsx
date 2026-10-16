import { afterEach, describe, expect, test } from "bun:test";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { type LineSeries, LineChart, MAX_TIP_ROWS, type Point, bandPath, ema, linePath, nearestX, pointAt } from "../../src/charts/LineChart";
import { TooltipHost, hideTip } from "../../src/charts/Tooltip";

afterEach(() => act(() => hideTip()));

const xs = Array.from({ length: 11 }, (_, i) => i * 100);
const up: LineSeries = { id: "up", name: "lr 3e-4", color: "var(--c1)", points: xs.map((x) => [x, x / 1000] as const) };
const down: LineSeries = { id: "down", name: "lr 1e-3", color: "var(--c2)", points: xs.map((x) => [x, 1 - x / 1000] as const) };

/** clientX that hovers data x `v` on a 420 px chart (plot from 44 to 410 px, x domain 0..1000). */
const at = (v: number): number => 44 + (366 * v) / 1000;

const svgOf = (container: HTMLElement): SVGSVGElement => container.querySelector("svg.chart") as SVGSVGElement;
const yLabels = (svg: Element): number[] => [...svg.querySelectorAll("text.yt")].map((t) => Number((t.textContent ?? "").replace("−", "-")));
const mantissa = (step: number): number => +(step / 10 ** Math.floor(Math.log10(step) + 1e-9)).toPrecision(6);

describe("geometry", () => {
  test("draws at the given pixel width: viewBox = width, text sizes come from CSS only", () => {
    for (const width of [320, 900]) {
      const { container, unmount } = render(<LineChart series={[up]} width={width} />);
      const svg = svgOf(container);
      expect([svg.getAttribute("width"), svg.getAttribute("viewBox")]).toEqual([String(width), `0 0 ${width} 190`]);
      for (const t of svg.querySelectorAll("text")) {
        expect(t.getAttribute("font-size")).toBeNull();
        expect((t as SVGTextElement).style.fontSize).toBe("");
      }
      unmount();
    }
  });

  test("y tick labels are nice numbers on one 1/2/2.5/5 step", () => {
    const { container } = render(<LineChart series={[up, down]} width={420} />);
    const ys = yLabels(svgOf(container));
    expect(ys).toEqual([0, 0.25, 0.5, 0.75, 1]);
    expect(mantissa((ys[1] ?? 0) - (ys[0] ?? 0))).toBe(2.5);
    const xt = [...svgOf(container).querySelectorAll("text.xt")].map((t) => t.textContent);
    expect(xt).toEqual(["0", "250", "500", "750", "1k"]);
  });

  test("hidden series are not drawn and do not stretch the y axis", () => {
    const big: LineSeries = { id: "big", name: "big", color: "var(--c3)", points: [[0, 100], [1000, 200]], hidden: true };
    const { container } = render(<LineChart series={[up, big]} width={420} />);
    const svg = svgOf(container);
    expect(svg.querySelectorAll("path.ln").length).toBe(1);
    expect(Math.max(...yLabels(svg))).toBeLessThanOrEqual(1.06);
  });

  test("NaN breaks the line into segments", () => {
    const gappy: LineSeries = { id: "g", name: "g", color: "var(--c1)", points: [[0, 1], [100, Number.NaN], [200, 2], [300, 3]] };
    const { container } = render(<LineChart series={[gappy]} width={420} />);
    const d = svgOf(container).querySelector("path.ln")?.getAttribute("d") ?? "";
    expect(d.match(/M/g)?.length).toBe(2);
  });

  test("a failed run ends in a ×, a running run in a dot", () => {
    const failed: LineSeries = { ...up, id: "f", failed: true, points: [[0, 0.1], [100, 0.2], [200, Number.NaN]] };
    const live: LineSeries = { ...down, id: "l", running: true };
    const { container } = render(<LineChart series={[failed, live]} width={420} />);
    const svg = svgOf(container);
    expect(svg.querySelectorAll("path.fail-x").length).toBe(1);
    const dot = svg.querySelector("circle.live");
    expect(dot?.getAttribute("fill")).toBe("var(--c2)");
    expect(dot?.getAttribute("cx")).toBe(String(at(1000)));
  });

  test("smoothing draws the raw line faint under the EMA line", () => {
    const { container, rerender } = render(<LineChart series={[up]} width={420} smoothing={0.6} />);
    expect(svgOf(container).querySelectorAll("path.ln.raw").length).toBe(1);
    rerender(<LineChart series={[up]} width={420} smoothing={0} />);
    expect(svgOf(container).querySelectorAll("path.ln.raw").length).toBe(0);
  });

  test("no data and one point draw without NaN", () => {
    const { container, rerender } = render(<LineChart series={[]} width={420} />);
    expect(svgOf(container).textContent).toBe("no data");
    rerender(<LineChart series={[{ id: "one", name: "one", color: "var(--c1)", points: [[0, 5]] }]} width={420} />);
    expect(svgOf(container).outerHTML).not.toContain("NaN");
    expect(yLabels(svgOf(container)).length).toBeGreaterThanOrEqual(2);
  });

  test("a series with one finite point draws a 3.5 px marker (a one-point path draws nothing)", () => {
    const one: LineSeries = { id: "one", name: "train_accuracy", color: "var(--c1)", points: [[0, Number.NaN], [10, 0.9], [20, Number.NaN]] };
    const { container } = render(<LineChart series={[one, up]} width={420} />);
    const dots = [...svgOf(container).querySelectorAll('g[data-id="one"] circle.mk')];
    expect(dots.map((c) => c.getAttribute("r"))).toEqual(["3.5"]);
    expect(dots[0]?.getAttribute("fill")).toBe("var(--c1)");
    // a series with more points keeps its line only
    expect(svgOf(container).querySelectorAll('g[data-id="up"] circle.mk')).toHaveLength(0);
  });

  test("highlight dims every other series", () => {
    const { container } = render(<LineChart series={[up, down]} width={420} highlight="down" />);
    const cls = [...svgOf(container).querySelectorAll("g[data-id] path.ln")].map((p) => p.getAttribute("class"));
    expect(cls).toEqual(["ln dim", "ln hi"]);
  });

  test("highlight by group id lights every series of that config", () => {
    const seeds: LineSeries[] = [
      { ...up, id: "r1", groupId: "g1" },
      { ...down, id: "r2", groupId: "g1" },
      { ...up, id: "r3", groupId: "g2" },
    ];
    const { container } = render(<LineChart series={seeds} width={420} highlight="g1" />);
    const cls = [...svgOf(container).querySelectorAll("g[data-id] path.ln")].map((p) => p.getAttribute("class"));
    expect(cls).toEqual(["ln hi", "ln hi", "ln dim"]);
    const marks = [...svgOf(container).querySelectorAll("g[data-id]")].map((g) => [g.getAttribute("data-id"), g.getAttribute("data-series")]);
    expect(marks).toEqual([["r1", "g1"], ["r2", "g1"], ["r3", "g2"]]);
  });

  test("each line carries data-series: its group id, else its own id", () => {
    const { container } = render(<LineChart series={[up, { ...down, groupId: "cfg" }]} width={420} />);
    const ids = [...svgOf(container).querySelectorAll("[data-series]")].map((g) => g.getAttribute("data-series"));
    expect(ids).toEqual(["up", "cfg"]);
  });

  test("a band is a faint area in the series colour behind its line, broken at gaps, inside the y range", () => {
    const banded: LineSeries = {
      ...up,
      band: [[0, 0.1, 0.3], [100, 0.2, 0.4], [200, Number.NaN, Number.NaN], [300, 0.3, 5], [400, 0.4, 5]],
    };
    const { container } = render(<LineChart series={[banded, down]} width={420} />);
    const svg = svgOf(container);
    const areas = [...svg.querySelectorAll("path.sarea")];
    expect(areas.length).toBe(2);
    expect(areas.every((a) => a.getAttribute("fill") === "var(--c1)")).toBe(true);
    const g = svg.querySelector('g[data-id="up"]') as Element;
    expect(g.firstElementChild?.getAttribute("class")).toBe("sarea");
    expect(svg.querySelector('g[data-id="down"] path.sarea')).toBeNull();
    // the band (up to 5) stretches the axis past the lines (0..1): ticks 0, 2, 4
    expect(Math.max(...yLabels(svg))).toBe(4);
  });
});

describe("hover", () => {
  test("snaps to the nearest step, draws a marker per series and one tooltip sorted high first", () => {
    const { container } = render(
      <>
        <LineChart series={[up, down]} width={420} />
        <TooltipHost />
      </>,
    );
    const svg = svgOf(container);
    fireEvent.mouseMove(svg.querySelector("rect.hit") as Element, { clientX: at(712), clientY: 40 });
    expect(svg.querySelector("line.xh")?.getAttribute("x1")).toBe(String(at(700)));
    expect(svg.querySelectorAll("circle.mk").length).toBe(2);
    const tip = screen.getByRole("tooltip");
    expect(tip.querySelector(".h")?.textContent).toBe("step 700");
    expect([...tip.querySelectorAll(".r")].map((r) => [r.querySelector("b")?.textContent, r.querySelector("span")?.textContent])).toEqual([
      ["0.7", "lr 3e-4"],
      ["0.3", "lr 1e-3"],
    ]);
    fireEvent.mouseLeave(svg.querySelector("rect.hit") as Element);
    expect(svg.querySelector("line.xh")).toBeNull();
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  test("charts of one crosshair group share the hovered step", () => {
    const { container } = render(
      <>
        <LineChart series={[up]} width={420} crosshairGroup="train" />
        <LineChart series={[down]} width={420} crosshairGroup="train" />
        <LineChart series={[down]} width={420} crosshairGroup="sys" />
      </>,
    );
    const [a, b, c] = [...container.querySelectorAll("svg.chart")];
    fireEvent.mouseMove((a as Element).querySelector("rect.hit") as Element, { clientX: at(300), clientY: 10 });
    expect(b?.querySelector("line.xh")?.getAttribute("x1")).toBe(String(at(300)));
    expect(b?.querySelectorAll("circle.mk").length).toBe(1);
    expect(c?.querySelector("line.xh")).toBeNull();
    fireEvent.mouseLeave((a as Element).querySelector("rect.hit") as Element);
    expect(b?.querySelector("line.xh")).toBeNull();
  });

  test("the tooltip lists at most 8 runs", () => {
    const many: LineSeries[] = Array.from({ length: 10 }, (_, i) => ({
      id: `s${i}`, name: `s${i}`, color: "var(--c0)", points: [[0, i], [100, i]],
    }));
    const { container } = render(
      <>
        <LineChart series={many} width={420} />
        <TooltipHost />
      </>,
    );
    fireEvent.mouseMove(svgOf(container).querySelector("rect.hit") as Element, { clientX: 400, clientY: 0 });
    const rows = screen.getByRole("tooltip").querySelectorAll(".r");
    expect(rows.length).toBe(MAX_TIP_ROWS);
    expect(rows[0]?.querySelector("b")?.textContent).toBe("9");
  });
});

describe("helpers", () => {
  test("ema keeps NaN gaps and smooths across them", () => {
    const pts: Point[] = [[0, 0], [1, 10], [2, Number.NaN], [3, 10]];
    const out = ema(pts, 0.5);
    expect(out.map((p) => p[1])).toEqual([0, 5, Number.NaN, 7.5]);
    expect(ema(pts, 0)).toEqual(pts);
  });

  test("linePath starts a new segment after a gap", () => {
    expect(linePath([[0, 0], [1, Number.NaN], [2, 2]], (x) => x * 10, (y) => y)).toBe("M0,0M20,2");
  });

  test("bandPath runs along hi, back along lo, one closed area per unbroken run", () => {
    const X = (x: number) => x * 10;
    const Y = (y: number) => y;
    expect(bandPath([[0, 1, 2], [1, 1, 2]], X, Y)).toBe("M0,2L10,2L10,1L0,1Z");
    expect(bandPath([[0, 1, 2], [1, Number.NaN, 2], [2, 1, 3], [3, 0, 3]], X, Y)).toBe("M20,3L30,3L30,0L20,1Z");
    expect(bandPath([], X, Y)).toBe("");
  });

  test("pointAt and nearestX pick the closest logged x, inside the series' range only", () => {
    const pts: Point[] = [[0, 1], [100, 2], [200, 3]];
    expect([pointAt(pts, 140)?.[0], pointAt(pts, 160)?.[0], pointAt(pts, 250), pointAt([], 0)]).toEqual([100, 200, null, null]);
    expect([nearestX([0, 100, 200], 149), nearestX([], 1)]).toEqual([100, null]);
  });
});

describe("time x axes", () => {
  // epoch seconds around 2026-10-15: 30 min of points, one a minute
  const T0 = 1_792_152_689;
  const wall: LineSeries = {
    id: "w", name: "wall", color: "var(--c1)",
    points: Array.from({ length: 31 }, (_, i) => [T0 + i * 60, i / 30] as const),
  };
  const xTicks = (svg: Element) => [...svg.querySelectorAll("text.xt")].map((t) => [t.textContent ?? "", Number(t.getAttribute("x"))] as const);
  const clock = (s: number, sec = false): string => {
    const d = new Date(s * 1000);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}${sec ? `:${p(d.getSeconds())}` : ""}`;
  };

  test("clock: the domain is the data extent (not from 0), ticks are HH:MM on whole minutes inside the plot", () => {
    const { container } = render(<LineChart series={[wall]} width={420} xAxis="clock" />);
    const svg = svgOf(container);
    const d = svg.querySelector("path.ln")?.getAttribute("d") ?? "";
    // the first point sits on the left edge of the plot, the last on the right
    expect(d.startsWith("M44,")).toBe(true);
    expect(d).toContain("L410,");
    const ticks = xTicks(svg);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    for (const [label, x] of ticks) {
      expect(label).toMatch(/^\d\d:\d\d$/);
      expect(x).toBeGreaterThanOrEqual(44);
      expect(x).toBeLessThanOrEqual(410);
    }
    expect(new Set(ticks.map(([l]) => l)).size).toBe(ticks.length);
    expect(ticks.map(([l]) => l)).not.toContain("1000M");
  });

  test("clock: the tooltip header is the wall-clock time of the hovered point", () => {
    const { container } = render(
      <>
        <LineChart series={[wall]} width={420} xAxis="clock" xLabel="wall time" />
        <TooltipHost />
      </>,
    );
    fireEvent.mouseMove(svgOf(container).querySelector("rect.hit") as Element, { clientX: 44, clientY: 40 });
    expect(screen.getByRole("tooltip").querySelector(".h")?.textContent).toBe(`wall time ${clock(T0, true)}`);
  });

  test("duration: ticks and tooltip carry units (s, m, h)", () => {
    const rel: LineSeries = { id: "r", name: "rel", color: "var(--c1)", points: [[0, 1], [1800, 2], [5400, 3]] };
    const { container } = render(
      <>
        <LineChart series={[rel]} width={420} xAxis="duration" xLabel="relative time" />
        <TooltipHost />
      </>,
    );
    const svg = svgOf(container);
    expect(xTicks(svg).map(([l]) => l)).toEqual(["0", "30m", "1h", "1.5h"]);
    fireEvent.mouseMove(svg.querySelector("rect.hit") as Element, { clientX: 410, clientY: 40 });
    expect(screen.getByRole("tooltip").querySelector(".h")?.textContent).toBe("relative time 1.5h");
  });

  test("duration: sub-second spans read in ms, short spans in s", () => {
    const fast: LineSeries = { id: "f", name: "f", color: "var(--c1)", points: [[0, 1], [0.0004, 2], [0.0008, 3]] };
    const { container, rerender } = render(<LineChart series={[fast]} width={420} xAxis="duration" />);
    const ms = xTicks(svgOf(container)).map(([l]) => l);
    expect(ms[0]).toBe("0");
    expect(ms.slice(1).every((l) => /^\d+(\.\d+)?ms$/.test(l))).toBe(true);
    const short: LineSeries = { id: "s", name: "s", color: "var(--c1)", points: [[0, 1], [45, 2]] };
    rerender(<LineChart series={[short]} width={420} xAxis="duration" />);
    expect(xTicks(svgOf(container)).map(([l]) => l)).toEqual(["0", "15s", "30s", "45s"]);
  });
});
