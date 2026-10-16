import { afterEach, expect, test } from "bun:test";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TIP_OFFSET, TooltipHost, hideTip, showTip, useTooltip } from "../../src/charts/Tooltip";

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

test("showTip draws one tooltip: a header, then rows with the value first", () => {
  render(<TooltipHost />);
  act(() =>
    showTip(100, 50, "step 1,000", [
      { color: "var(--c1)", value: "0.912", name: "lr 3e-4" },
      { value: "2", name: "seeds" },
    ]),
  );
  const tip = screen.getByRole("tooltip");
  expect(tip.querySelector(".h")?.textContent).toBe("step 1,000");
  const rows = [...tip.querySelectorAll(".r")].map((r) => [...r.children].map((c) => c.textContent));
  expect(rows).toEqual([["", "0.912", "lr 3e-4"], ["", "2", "seeds"]]);
  expect((tip.querySelector(".r .k") as HTMLElement).style.background).toBe("var(--c1)");
  expect(tip.style.left).toBe(`${100 + TIP_OFFSET}px`);
  expect(tip.style.top).toBe(`${50 + TIP_OFFSET}px`);
  act(() => hideTip());
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("tooltip text is text, never HTML", () => {
  render(<TooltipHost />);
  act(() => showTip(0, 0, "<b>x</b>", [{ value: "<i>1</i>", name: "<img src=x>" }]));
  const tip = screen.getByRole("tooltip");
  expect(tip.querySelectorAll("img, i:not(.k)").length).toBe(0);
  expect(tip.textContent).toContain("<img src=x>");
  act(() => hideTip());
});

test("near the window's right edge the tooltip stays inside it", () => {
  render(<TooltipHost />);
  act(() => showTip(window.innerWidth + 500, 10, "far", []));
  expect(screen.getByRole("tooltip").style.left).toBe(`${window.innerWidth - 8}px`);
  act(() => hideTip());
});
