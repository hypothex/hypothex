import { describe, expect, test } from "bun:test";
import { render } from "@testing-library/react";
import { BarPanel } from "../../src/charts/BarPanel";
import { DotCIChart } from "../../src/charts/DotCIChart";
import { LineChart } from "../../src/charts/LineChart";
import { ParallelCoords } from "../../src/charts/ParallelCoords";
import { ScatterPareto } from "../../src/charts/ScatterPareto";
import { Panel } from "../../src/chrome/Panel";

const charts = {
  line: <LineChart series={[{ id: "a", name: "a", color: "var(--c1)", points: [[0, 1], [1, 2]] }]} width={400} />,
  bars: <BarPanel rows={[{ id: "a", name: "a", color: "var(--c1)", value: 0.5 }]} metric="top1" width={400} />,
  dots: <DotCIChart rows={[{ id: "a", name: "a", color: "var(--c1)", mean: 0.5 }]} width={400} />,
  parallel: (
    <ParallelCoords
      axes={[{ key: "lr", label: "lr" }, { key: "top1", label: "top1" }]}
      lines={[{ id: "a", name: "a", values: { lr: 1, top1: 0.5 } }, { id: "b", name: "b", values: { lr: 2, top1: 0.6 } }]}
      colorBy="top1"
      width={400}
    />
  ),
  scatter: <ScatterPareto points={[{ id: "a", name: "a", color: "var(--c1)", x: 1, y: 0.5 }]} width={400} />,
};

describe("chart svgs are named by their panel title", () => {
  for (const [kind, chart] of Object.entries(charts)) {
    test(kind, () => {
      const { container } = render(<Panel title="val/loss">{chart}</Panel>);
      const svg = container.querySelector("svg.chart");
      expect(svg?.getAttribute("aria-label")).toBe("val/loss");
      expect(svg?.getAttribute("role")).toBe(kind === "dots" ? "group" : "img");
    });
  }

  test("the panel's accessible label wins over its title, and a chart outside a panel still has a name", () => {
    const { container } = render(<Panel title="top1" label="top1 by config">{charts.line}</Panel>);
    expect(container.querySelector("svg.chart")?.getAttribute("aria-label")).toBe("top1 by config");
    const bare = render(charts.line);
    expect(bare.container.querySelector("svg.chart")?.getAttribute("aria-label")).toBe("Line chart");
  });
});
