import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TIP_OFFSET, useTooltip } from "../../src/charts/Tooltip";

afterEach(cleanup);

function Chart() {
  const tip = useTooltip();
  return (
    <div>
      <svg>
        <rect data-testid="mark" tabIndex={0} {...tip.bind("mean 0.9222\nseeds 3")} />
      </svg>
      {tip.node}
    </div>
  );
}

test("hover shows the text next to the pointer and leave hides it", () => {
  render(<Chart />);
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.mouseEnter(screen.getByTestId("mark"), { clientX: 10, clientY: 20 });
  const tip = screen.getByRole("tooltip");
  expect(tip.textContent).toBe("mean 0.9222\nseeds 3");
  expect(tip.style.left).toBe(`${10 + TIP_OFFSET}px`);
  expect(tip.style.top).toBe(`${20 + TIP_OFFSET}px`);
  fireEvent.mouseMove(screen.getByTestId("mark"), { clientX: 30, clientY: 40 });
  expect(screen.getByRole("tooltip").style.left).toBe(`${30 + TIP_OFFSET}px`);
  fireEvent.mouseLeave(screen.getByTestId("mark"));
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("keyboard focus shows the tooltip and blur hides it", () => {
  render(<Chart />);
  fireEvent.focus(screen.getByTestId("mark"));
  expect(screen.getByRole("tooltip").textContent).toBe("mean 0.9222\nseeds 3");
  fireEvent.blur(screen.getByTestId("mark"));
  expect(screen.queryByRole("tooltip")).toBeNull();
});
