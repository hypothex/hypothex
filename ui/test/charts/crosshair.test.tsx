import { expect, test } from "bun:test";
import { fireEvent, render, screen } from "@testing-library/react";
import { getCrosshair, useCrosshair } from "../../src/charts/crosshair";

function Probe({ group, id }: { group: string; id: string }) {
  const [x, setX] = useCrosshair(group);
  return (
    <button type="button" data-testid={id} onClick={() => setX(42)} onDoubleClick={() => setX(null)}>
      {x === null ? "none" : String(x)}
    </button>
  );
}

test("every chart of one group sees the hovered x; other groups do not", () => {
  const { unmount } = render(
    <>
      <Probe group="train" id="a" />
      <Probe group="train" id="b" />
      <Probe group="sys" id="c" />
    </>,
  );
  fireEvent.click(screen.getByTestId("a"));
  expect(["a", "b", "c"].map((id) => screen.getByTestId(id).textContent)).toEqual(["42", "42", "none"]);
  fireEvent.doubleClick(screen.getByTestId("b"));
  expect(screen.getByTestId("a").textContent).toBe("none");
  fireEvent.click(screen.getByTestId("a"));
  unmount();
  expect(getCrosshair("train")).toBeNull();
});
