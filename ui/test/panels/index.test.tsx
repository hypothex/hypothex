import { afterEach, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { PANELS, Panel, panelFor, type PanelProps } from "../../src/panels/index";
import { StatStrip } from "../../src/panels/StatStrip";

afterEach(cleanup);

test("the registry maps stat_strip to StatStrip and rejects unknown types", () => {
  expect(panelFor("stat_strip")).toBe(StatStrip);
  expect(panelFor("pie")).toBeNull();
  expect(panelFor("constructor")).toBeNull();
});

test("Panel renders the registered component", () => {
  render(
    <Panel result={{ type: "stat_strip", title: "", rows: [{ label: "runs", value: 12 }] }} />,
  );
  expect(screen.getByText("runs")).toBeTruthy();
  expect(screen.getByText("12")).toBeTruthy();
});

test("Panel shows an error box for an unknown type", () => {
  render(<Panel result={{ type: "pie" as never, title: "", rows: [] }} />);
  expect(screen.getByRole("alert").textContent).toBe("Unknown panel type: pie");
});

test("Panel contains a panel that throws", () => {
  const Broken = (_: PanelProps) => {
    throw new Error("bad rows");
  };
  const before = PANELS.table;
  PANELS.table = Broken;
  const err = console.error;
  console.error = () => {};
  try {
    render(<Panel result={{ type: "table", title: "", rows: [] }} />);
    expect(screen.getByRole("alert").textContent).toBe("Panel failed: bad rows");
  } finally {
    console.error = err;
    if (before) PANELS.table = before;
    else delete PANELS.table;
  }
});
