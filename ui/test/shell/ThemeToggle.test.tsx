import { describe, expect, test } from "bun:test";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { THEME_KEY, ThemeToggle, currentTheme, toggleTheme } from "../../src/shell/ThemeToggle";

describe("ThemeToggle", () => {
  test("starts light and offers Dark", () => {
    render(<ThemeToggle />);
    expect(currentTheme()).toBe("light");
    expect(screen.getByRole("button", { name: "Switch colour mode" }).textContent).toBe("Dark");
  });

  test("click switches to dark, stores it, and relabels", () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Switch colour mode" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch colour mode" }).textContent).toBe("Light");
  });

  test("a toggle from elsewhere (the palette) updates the label", () => {
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    expect(screen.getByRole("button").textContent).toBe("Light");
    act(() => {
      expect(toggleTheme()).toBe("light");
    });
    expect(screen.getByRole("button").textContent).toBe("Dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
  });

  test("still switches when storage is unavailable", () => {
    const real = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    const attempts: string[] = [];
    const blocked = {
      getItem: () => null,
      setItem: (key: string) => {
        attempts.push(key);
        throw new Error("SecurityError");
      },
    };
    Object.defineProperty(globalThis, "localStorage", { value: blocked, configurable: true });
    try {
      render(<ThemeToggle />);
      fireEvent.click(screen.getByRole("button", { name: "Switch colour mode" }));
      expect(document.documentElement.dataset.theme).toBe("dark");
      expect(screen.getByRole("button").textContent).toBe("Light");
      expect(attempts).toEqual(["hx-theme"]);
    } finally {
      if (real) Object.defineProperty(globalThis, "localStorage", real);
    }
  });
});
