/**
 * Keyboard focus for popover menus (WAI-ARIA menu button pattern): the first item takes
 * focus when the menu opens, the arrow keys (and Home/End) move between enabled items,
 * and focus goes back to the trigger when the menu closes while focus was inside it (not
 * after Tab moved focus out).
 */
import { type KeyboardEvent, type RefObject, useEffect, useRef } from "react";

/** Focusable items of a popover: menu items, checkboxes and plain buttons that are enabled. */
const ITEMS = '[role^="menuitem"]:not(:disabled), input:not(:disabled), button:not(:disabled)';

function items(root: HTMLElement | null): HTMLElement[] {
  return root ? [...root.querySelectorAll<HTMLElement>(ITEMS)] : [];
}

/**
 * Move focus into the menu when `open` turns true; give it back to `trigger` when the
 * menu closes while focus was inside (a click elsewhere keeps its own focus).
 *
 * Examples
 * --------
 * >>> useMenuFocus(open, menuRef, buttonRef);
 */
export function useMenuFocus(open: boolean, menu: RefObject<HTMLElement | null>, trigger: RefObject<HTMLElement | null>): void {
  const inside = useRef(false);
  useEffect(() => {
    if (open) {
      items(menu.current)[0]?.focus();
      const root = menu.current;
      const track = (): void => {
        inside.current = root?.contains(document.activeElement) ?? false;
      };
      // focus moving to another element outside (Tab out) leaves the menu; focus moving to
      // nothing (the focused item removed, a click on plain page) keeps the last state
      const leave = (e: FocusEvent): void => {
        const to = e.relatedTarget;
        if (to instanceof Node && !root?.contains(to)) inside.current = false;
      };
      track();
      root?.addEventListener("focusin", track);
      root?.addEventListener("focusout", leave);
      return () => {
        root?.removeEventListener("focusin", track);
        root?.removeEventListener("focusout", leave);
      };
    }
    // closed: the menu is gone, so focus that was inside it fell to the body
    const lost = document.activeElement === null || document.activeElement === document.body;
    if (inside.current && lost) trigger.current?.focus();
    inside.current = false;
    return undefined;
  }, [open, menu, trigger]);
}

/**
 * Arrow keys for a menu's `onKeyDown`: Down/Up move to the next/previous enabled item
 * (wrapping), Home/End to the first/last.
 *
 * Examples
 * --------
 * >>> <div role="menu" onKeyDown={menuArrowKeys}>…</div>
 */
export function menuArrowKeys(e: KeyboardEvent<HTMLElement>): void {
  const list = items(e.currentTarget);
  if (list.length === 0) return;
  const at = list.indexOf(document.activeElement as HTMLElement);
  const next =
    e.key === "ArrowDown" ? (at + 1) % list.length
    : e.key === "ArrowUp" ? (at <= 0 ? list.length - 1 : at - 1)
    : e.key === "Home" ? 0
    : e.key === "End" ? list.length - 1
    : null;
  if (next === null) return;
  e.preventDefault();
  list[next]?.focus();
}
