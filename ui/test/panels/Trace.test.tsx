import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { kTok, shortText, TracePanel } from "../../src/panels/Trace";

afterEach(cleanup);

const STEPS = [
  {
    turn: 1,
    tool: "search",
    args: { smiles: "CCO" },
    result: "12 hits",
    tokens_in: 1200,
    tokens_out: 50,
    seconds: 1.2,
    error: null,
  },
  {
    turn: 2,
    tool: "expand",
    args: { node: 3 },
    result: null,
    tokens_in: 3400,
    tokens_out: 80,
    seconds: 2.5,
    error: "tool timeout",
  },
  {
    turn: 3,
    tool: "expand",
    args: { node: 3 },
    result: null,
    tokens_in: 15000,
    tokens_out: 120,
    seconds: 4.0,
    error: "loop detector: 3rd identical call",
  },
];

const trace = (rows: Record<string, unknown>[], meta: Record<string, unknown>): PanelResult => ({
  type: "trace",
  title: "Attempt",
  rows,
  meta,
});

const row = (c: HTMLElement, turn: number) =>
  c.querySelector(`tbody tr[data-turn="${turn}"]`) as HTMLElement;

describe("kTok and shortText", () => {
  test("token counts are short", () => {
    expect(kTok(250)).toBe("250");
    expect(kTok(1200)).toBe("1.2k");
    expect(kTok(15000)).toBe("15k");
    expect(kTok(19600)).toBe("20k");
    expect(kTok(2_500_000)).toBe("2.50M");
  });

  test("JSON values are one line and cut with an ellipsis", () => {
    expect(shortText({ smiles: "CCO" })).toBe('{"smiles":"CCO"}');
    expect(shortText("x".repeat(200), 10)).toBe(`${"x".repeat(9)}…`);
    expect(shortText(null)).toBe("");
  });
});

describe("TracePanel", () => {
  const meta = { run_id: "r-abc", example_id: "t042", failed_turn: 3 };

  test("marks the failing turn and flags earlier errors as warnings", () => {
    const { container } = render(<TracePanel result={trace(STEPS, meta)} />);
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
    expect(row(container, 3).dataset.failed).toBe("true");
    expect(row(container, 1).dataset.failed).toBe("false");
    expect(row(container, 2).dataset.warn).toBe("true");
    expect(row(container, 3).dataset.warn).toBe("false");
    expect(row(container, 3).textContent).toContain("loop detector: 3rd identical call");
    expect(row(container, 2).textContent).toContain("tool timeout");
    expect(row(container, 1).textContent).toContain('{"smiles":"CCO"}');
    expect(row(container, 1).textContent).toContain("12 hits");
  });

  test("footer sums turns, tokens and seconds", () => {
    render(<TracePanel result={trace(STEPS, meta)} />);
    expect(screen.getByTestId("turns").textContent).toBe("3");
    expect(screen.getByTestId("sum-in").textContent).toBe("20k");
    expect(screen.getByTestId("sum-out").textContent).toBe("250");
    expect(screen.getByTestId("sum-s").textContent).toBe("7.7");
  });

  test("seconds bars scale to the slowest turn", () => {
    render(<TracePanel result={trace(STEPS, meta)} />);
    const widths = screen.getAllByTestId("sbar").map((el) => el.style.width);
    expect(widths).toEqual(["17px", "35px", "56px"]);
  });

  test("caption links the run and names the failing turn", () => {
    render(<TracePanel result={trace(STEPS, meta)} />);
    expect(screen.getByRole("link", { name: "r-abc" }).getAttribute("href")).toBe("/r/r-abc");
    expect(screen.getByText(/failed at turn 3/)).toBeTruthy();
  });

  test("without failed_turn no row is marked failed", () => {
    const { container } = render(<TracePanel result={trace(STEPS, { run_id: "r-abc" })} />);
    expect(container.querySelectorAll('tr[data-failed="true"]').length).toBe(0);
  });

  test("empty trace says so", () => {
    render(<TracePanel result={trace([], {})} />);
    expect(screen.getByText("No trace")).toBeTruthy();
  });
});
