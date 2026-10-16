import { afterEach, expect, test } from "bun:test";
import { fireEvent, render, screen } from "@testing-library/react";
import { type PCAxis, type PCLine, ParallelCoords, SEQ_RAMP, seqColor } from "../../src/charts/ParallelCoords";
import { TooltipHost, hideTip } from "../../src/charts/Tooltip";

afterEach(() => hideTip());

const axes: PCAxis[] = [
  { key: "lr", label: "lr", values: ["1e-4", "3e-4", "1e-3"] },
  { key: "beam", label: "beam", values: ["1", "5", "10"] },
  { key: "top1", label: "top1" },
];
const lines: PCLine[] = [
  { id: "r1", name: "lr 1e-4 · beam 1", values: { lr: "1e-4", beam: "1", top1: 0.889 } },
  { id: "r2", name: "lr 3e-4 · beam 10", values: { lr: "3e-4", beam: "10", top1: 0.9121 } },
  { id: "r3", name: "lr 3e-4 · beam 10 · seed 2", values: { lr: "3e-4", beam: "10", top1: 0.9101 } },
  { id: "r4", name: "incomplete", values: { lr: "1e-3", top1: 0.88 } },
];

test("one axis per param plus the score, titles on top, haloed tick labels", () => {
  const { container } = render(<ParallelCoords axes={axes} lines={lines} width={600} colorBy="top1" />);
  const svg = container.querySelector("svg.chart") as SVGSVGElement;
  expect(svg.getAttribute("viewBox")).toBe("0 0 600 240");
  expect(svg.querySelectorAll("line.ax").length).toBe(3);
  expect([...svg.querySelectorAll("text.axis-t")].map((t) => t.textContent)).toEqual(["lr", "beam", "top1"]);
  const halo = [...svg.querySelectorAll("text.halo")].map((t) => t.textContent);
  expect(halo.slice(0, 3)).toEqual(["1e-4", "3e-4", "1e-3"]);
  const numeric = halo.slice(6).map(Number);
  expect(numeric.length).toBeGreaterThanOrEqual(2);
  expect(numeric.every((v, i) => i === 0 || v > (numeric[i - 1] ?? 0))).toBe(true);
});

test("complete lines only, coloured by the score, best drawn last and darkest", () => {
  const { container } = render(<ParallelCoords axes={axes} lines={lines} width={600} colorBy="top1" />);
  const paths = [...container.querySelectorAll("path.pc")];
  expect(paths.length).toBe(3);
  expect(paths.at(-1)?.getAttribute("stroke")).toBe(SEQ_RAMP[5]);
  expect(paths[0]?.getAttribute("stroke")).toBe(SEQ_RAMP[0]);
  // r2 and r3 share lr and beam: spread apart, not drawn on top of each other
  const starts = paths.slice(1).map((p) => (p.getAttribute("d") ?? "").split(" ")[0]);
  expect(starts[0]).not.toBe(starts[1]);
});

test("hovering a line thickens it and lists its values", () => {
  const { container } = render(
    <>
      <ParallelCoords axes={axes} lines={lines} width={600} colorBy="top1" format={(v) => v.toFixed(4)} />
      <TooltipHost />
    </>,
  );
  const best = [...container.querySelectorAll("path.pc")].at(-1) as Element;
  fireEvent.mouseMove(best, { clientX: 1, clientY: 1 });
  expect(best.getAttribute("class")).toBe("pc on");
  const tip = screen.getByRole("tooltip");
  expect(tip.querySelector(".h")?.textContent).toBe("lr 3e-4 · beam 10");
  expect([...tip.querySelectorAll(".r")].map((r) => r.textContent)).toEqual(["3e-4lr", "10beam", "0.9121top1"]);
});

test("lower is better: low values are dark and drawn last", () => {
  const latency: PCAxis[] = [
    { key: "batch", label: "batch", values: ["8", "32"] },
    { key: "p95", label: "p95 ms" },
  ];
  const rows: PCLine[] = [
    { id: "fast", name: "batch 8", values: { batch: "8", p95: 41.2 } },
    { id: "mid", name: "batch 16", values: { batch: "8", p95: 50 } },
    { id: "slow", name: "batch 32", values: { batch: "32", p95: 58 } },
  ];
  const { container } = render(<ParallelCoords axes={latency} lines={rows} width={500} colorBy="p95" higherIsBetter={false} />);
  const paths = [...container.querySelectorAll("path.pc")];
  expect(paths.at(-1)?.getAttribute("stroke")).toBe(SEQ_RAMP[5]);
  expect(paths[0]?.getAttribute("stroke")).toBe(SEQ_RAMP[0]);
  const { container: up } = render(<ParallelCoords axes={latency} lines={rows} width={500} colorBy="p95" />);
  expect([...up.querySelectorAll("path.pc")].at(-1)?.getAttribute("stroke")).toBe(SEQ_RAMP[5]);
});

test("seqColor clamps to the ramp", () => {
  expect([seqColor(-1), seqColor(0), seqColor(0.5), seqColor(1), seqColor(2)]).toEqual([
    SEQ_RAMP[0], SEQ_RAMP[0], SEQ_RAMP[3], SEQ_RAMP[5], SEQ_RAMP[5],
  ]);
});

test("null or blank values make a line incomplete, not zero", () => {
  const holes: PCLine[] = [
    ...lines.slice(0, 2),
    { id: "n1", name: "null score", values: { lr: "1e-4", beam: "5", top1: null } },
    { id: "n2", name: "blank score", values: { lr: "1e-4", beam: "5", top1: "" } },
  ];
  const { container } = render(<ParallelCoords axes={axes} lines={holes} width={600} colorBy="top1" />);
  expect(container.querySelectorAll("path.pc").length).toBe(2);
});

test("no complete lines: a calm message, no NaN", () => {
  const { container } = render(<ParallelCoords axes={axes} lines={[lines[3] as PCLine]} width={600} colorBy="top1" />);
  expect(container.querySelectorAll("path.pc").length).toBe(0);
  expect(container.textContent).toContain("no runs");
  expect(container.innerHTML).not.toContain("NaN");
});
