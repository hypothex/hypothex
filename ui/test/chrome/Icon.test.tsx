import { expect, test } from "bun:test";
import { render, screen } from "@testing-library/react";
import { ICON_NAMES, Icon } from "../../src/chrome/Icon";

test("every icon is one decorative stroke svg in currentColor", () => {
  expect(ICON_NAMES.length).toBe(21);
  for (const name of ICON_NAMES) {
    const { container, unmount } = render(<Icon name={name} />);
    const svg = container.querySelector("svg") as SVGSVGElement;
    expect([name, svg.getAttribute("aria-hidden"), svg.getAttribute("stroke"), svg.getAttribute("fill")]).toEqual([
      name,
      "true",
      "currentColor",
      "none",
    ]);
    expect(svg.getAttribute("viewBox")).toMatch(/^0 0 1[0246] 1[0246]$/);
    expect(svg.children.length).toBeGreaterThan(0);
    unmount();
  }
});

test("a label makes it an image with a name; size sets width and height; the spinner spins", () => {
  render(<Icon name="warn" label="lost" size={18} />);
  const img = screen.getByRole("img", { name: "lost" });
  expect([img.getAttribute("width"), img.getAttribute("height")]).toEqual(["18", "18"]);
  const { container } = render(<Icon name="spinner" />);
  expect(container.querySelector(".spin")).not.toBeNull();
});
