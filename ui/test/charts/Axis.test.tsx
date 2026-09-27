import { afterEach, expect, test } from "bun:test";
import { cleanup, render } from "@testing-library/react";
import { AxisBottom, AxisLeftLabels, GridX, GridY } from "../../src/charts/Axis";

afterEach(cleanup);

const x = (v: number) => 100 + v * 10;

test("AxisBottom draws a baseline, one tick per value, labels and caption", () => {
  const { container } = render(
    <svg>
      <AxisBottom x={x} ticks={[0, 5, 10]} y={50} x0={0} x1={300} format={(v) => `${v}%`} label="accuracy" />
    </svg>,
  );
  const lines = container.querySelectorAll("line.axis");
  expect(lines.length).toBe(4);
  const tick = lines[2] as SVGLineElement;
  expect(tick.getAttribute("x1")).toBe("150");
  expect(tick.getAttribute("y2")).toBe("54");
  const labels = [...container.querySelectorAll("text.tk")].map((t) => t.textContent);
  expect(labels).toEqual(["0%", "5%", "10%"]);
  const caption = container.querySelector("text.lbl-s");
  expect(caption?.textContent).toBe("accuracy");
  expect(caption?.getAttribute("x")).toBe("300");
  expect(caption?.getAttribute("text-anchor")).toBe("end");
});

test("AxisBottom labels every n-th tick only", () => {
  const { container } = render(
    <svg>
      <AxisBottom x={x} ticks={[0, 1, 2, 3, 4]} y={0} x0={0} x1={10} format={String} every={2} />
    </svg>,
  );
  const labels = [...container.querySelectorAll("text.tk")].map((t) => t.textContent);
  expect(labels).toEqual(["0", "2", "4"]);
  expect(container.querySelector("text.lbl-s")).toBeNull();
});

test("grids and left labels sit at the scaled positions", () => {
  const { container } = render(
    <svg>
      <GridX x={x} ticks={[1, 2]} y0={0} y1={80} />
      <GridY y={x} ticks={[3]} x0={5} x1={95} />
      <AxisLeftLabels y={x} ticks={[3]} x={40} format={(v) => v.toFixed(1)} />
    </svg>,
  );
  const grid = [...container.querySelectorAll("line.grid")];
  expect(grid.map((l) => l.getAttribute("x1"))).toEqual(["110", "120", "5"]);
  expect(grid[2]?.getAttribute("y1")).toBe("130");
  const lbl = container.querySelector(".axis-l text");
  expect(lbl?.textContent).toBe("3.0");
  expect(lbl?.getAttribute("y")).toBe("134");
});
