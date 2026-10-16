import { afterEach, expect, test } from "bun:test";
import { act, render, screen } from "@testing-library/react";
import { Fit } from "../../src/charts/Fit";
import { type FakeResize, fakeResize } from "./resize";

let ro: FakeResize | null = null;
afterEach(() => ro?.restore());

test("draws nothing until it has a width, then at the floored pixel width", () => {
  ro = fakeResize(0);
  render(<Fit>{(w) => <svg data-testid="c" width={w} />}</Fit>);
  expect(screen.queryByTestId("c")).toBeNull();
  act(() => ro?.resize(412.7));
  expect(screen.getByTestId("c").getAttribute("width")).toBe("412");
  act(() => ro?.resize(900));
  expect(screen.getByTestId("c").getAttribute("width")).toBe("900");
});

test("minHeight reserves the chart's space before the first measure", () => {
  ro = fakeResize(0);
  const { container } = render(<Fit minHeight={190}>{() => <svg />}</Fit>);
  const box = container.querySelector(".fit") as HTMLElement;
  expect(box.style.minHeight).toBe("190px");
});

test("a later zero width (hidden tab) keeps the last drawing", () => {
  ro = fakeResize(300);
  render(<Fit>{(w) => <svg data-testid="c" width={w} />}</Fit>);
  act(() => ro?.resize(0));
  expect(screen.getByTestId("c").getAttribute("width")).toBe("300");
});
