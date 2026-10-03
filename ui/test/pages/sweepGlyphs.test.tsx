import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { RUN_LIST_MAX, RunGlyph, SweepProgress, SweepRunList } from "../../src/pages/components/SweepGlyphs";
import type { RunGlyphState, SweepCellRun } from "../../src/pages/components/SweepModel";
import { SWEEP_CSS, SweepStyles } from "../../src/pages/components/SweepStyles";
import { makeSummary } from "./sweepFixtures";

afterEach(cleanup);

describe("sweep glyphs", () => {
  test("one glyph per run state", () => {
    const states: RunGlyphState[] = ["finished", "running", "queued", "stale", "failed", "lost", "killed"];
    const { container } = render(
      <>
        {states.map((s) => (
          <RunGlyph key={s} state={s} />
        ))}
      </>,
    );
    const svgs = [...container.querySelectorAll("svg.rg")];
    expect(svgs.map((s) => s.getAttribute("data-glyph"))).toEqual(states);
    expect(svgs.every((s) => s.getAttribute("aria-hidden") === "true")).toBe(true);
    expect(container.querySelectorAll("path.x")).toHaveLength(3);
    expect(container.querySelector('[data-glyph="stale"] path.half')).not.toBeNull();
  });

  test("every state has its own shape, not only its own colour", () => {
    const states: RunGlyphState[] = ["finished", "running", "queued", "stale", "failed", "lost", "killed"];
    const { container } = render(
      <>
        {states.map((s) => (
          <RunGlyph key={s} state={s} />
        ))}
      </>,
    );
    const svgs = [...container.querySelectorAll("svg.rg")];
    // Fill against ring is set by class, so the full markup tells all seven apart.
    expect(new Set(svgs.map((svg) => svg.innerHTML)).size).toBe(states.length);
    // The three cross states differ by colour class, so their geometry alone must differ.
    const geometry = (state: RunGlyphState): string =>
      container.querySelector(`[data-glyph="${state}"]`)?.innerHTML.replace(/\sclass="[^"]*"/g, "") ?? "";
    expect(new Set(["failed", "lost", "killed"].map((s) => geometry(s as RunGlyphState))).size).toBe(3);
    expect(container.querySelector('[data-glyph="killed"] circle.x-ring')).not.toBeNull();
    expect(container.querySelector('[data-glyph="lost"] circle.x-ring')).not.toBeNull();
    expect(container.querySelector('[data-glyph="failed"] circle')).toBeNull();
  });

  test("a cell's run list shows six runs and counts the rest", () => {
    const runs: SweepCellRun[] = Array.from({ length: 8 }, (_, i) => ({
      run_id: `20261003-x-r${i}`,
      status: "finished",
      seed: i + 1,
    }));
    render(<SweepRunList runs={runs} stateOf={(_id, fallback) => fallback ?? "queued"} />);
    const links = screen.getAllByRole("link");
    expect(RUN_LIST_MAX).toBe(6);
    expect(links.map((a) => a.textContent)).toEqual(["r0", "r1", "r2", "r3", "r4", "r5"]);
    expect(links[0]?.getAttribute("href")).toBe("/r/20261003-x-r0");
    expect(links[0]?.getAttribute("title")).toBe("r0, seed 1, finished");
    expect(screen.getByText("+2").getAttribute("title")).toBe("2 more runs");
  });

  test("the progress strip has one segment per run", () => {
    render(<SweepProgress counts={makeSummary().counts} />);
    const strip = screen.getByRole("img", { name: "5 finished, 1 running, 1 queued, 1 failed" });
    expect([...strip.querySelectorAll("i")].map((i) => i.className)).toEqual([
      "f",
      "f",
      "f",
      "f",
      "f",
      "r",
      "q",
      "x",
    ]);
  });

  test("SweepStyles injects the sweep CSS", () => {
    const { container } = render(<SweepStyles />);
    expect(container.querySelector('style[data-hx="sweep"]')?.textContent).toBe(SWEEP_CSS);
    expect(SWEEP_CSS).toContain(".page .heat td.c.best");
    expect(SWEEP_CSS).toContain(".page .prog i.x");
  });
});
