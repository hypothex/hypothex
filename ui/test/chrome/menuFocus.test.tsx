import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { menuArrowKeys, useMenuFocus } from "../../src/chrome/menuFocus";

afterEach(cleanup);

function Harness() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useMenuFocus(open, menu, trigger);
  return (
    <>
      <button ref={trigger} type="button" onClick={() => setOpen((o) => !o)}>
        Menu
      </button>
      <button type="button">Elsewhere</button>
      <button type="button" onClick={() => setOpen(false)}>
        Close
      </button>
      {open ? (
        <div ref={menu} role="menu" onKeyDown={menuArrowKeys}>
          <button type="button" role="menuitem">
            One
          </button>
          <button type="button" role="menuitem" onClick={() => setOpen(false)}>
            Two
          </button>
        </div>
      ) : null}
    </>
  );
}

/** Whether the button or menu item named `name` has focus. */
const active = (name: string): boolean =>
  document.activeElement === (screen.queryByRole("menuitem", { name }) ?? screen.getByRole("button", { name }));

test("focus goes back to the trigger when the menu closes from inside", () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Menu" }));
  expect(active("One")).toBe(true);
  const two = screen.getByRole("menuitem", { name: "Two" });
  two.focus();
  fireEvent.click(two);
  expect(screen.queryByRole("menu")).toBeNull();
  // the item that had focus is gone; the trigger takes it back
  expect(active("Menu")).toBe(true);
});

test("after Tab leaves the menu, closing it does not pull focus back", () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Menu" }));
  expect(active("One")).toBe(true);
  // Tab out to another control, then that control loses focus (a click on plain page)
  screen.getByRole("button", { name: "Elsewhere" }).focus();
  (document.activeElement as HTMLElement).blur();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("menu")).toBeNull();
  expect(active("Menu")).toBe(false);
});
