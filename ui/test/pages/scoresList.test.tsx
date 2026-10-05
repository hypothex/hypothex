import { expect, test } from "bun:test";
import { cleanup, screen } from "@testing-library/react";
import { ScoresList } from "../../src/pages/components/ScoresList";
import { renderWithClient } from "./helpers";

test("logged names cap at 20, clip each at 48, and give an exact remainder", () => {
  renderWithClient(<ScoresList scores={[]} metricNames={["x".repeat(200), ...Array.from({ length: 21 }, (_, n) => `metric${n}`)]} primary={null} />);
  const line = screen.getByText(/logged:/);
  expect(line.textContent).toContain("+2");
  expect(line.textContent).not.toContain("metric19");
  expect(line.textContent).not.toContain("x".repeat(49));
});

test("zero, twenty, and twenty-one logged names have exact remainder counts", () => {
  for (const n of [0, 20, 21]) {
    renderWithClient(<ScoresList scores={[]} metricNames={Array.from({ length: n }, (_, i) => `m${i}`)} primary={null} />);
    const line = screen.queryByText(/logged:/);
    if (n === 0) expect(line).toBeNull();
    else {
      expect(line?.textContent).toContain("m19");
      expect(line?.textContent?.endsWith(" +1")).toBe(n === 21);
      expect(line?.textContent).not.toContain("m20");
    }
    cleanup();
  }
});
