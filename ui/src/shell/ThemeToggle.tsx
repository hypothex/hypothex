/**
 * Light/dark switch. The theme lives on `<html data-theme>` (set before first paint by the
 * script in index.html) and in `localStorage["hx-theme"]`.
 */
import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
export const THEME_KEY = "hx-theme";
const THEME_EVENT = "hx:theme";

/** The theme currently on `<html>`; anything but "dark" is light. */
export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

/** Apply a theme, remember it, and notify `useTheme` subscribers. */
export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // storage can be disabled; the theme still applies for this page
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

/** Switch to the other theme and return it. */
export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(THEME_EVENT, onChange);
  return () => window.removeEventListener(THEME_EVENT, onChange);
}

/** The current theme; re-renders when it changes (charts use this for canvas colours). */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => "light");
}

/** Header button; its label names the mode it switches to, as in the mockup. */
export function ThemeToggle() {
  const theme = useTheme();
  return (
    <button className="theme" type="button" aria-label="Switch colour mode" onClick={toggleTheme}>
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        <circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M7 1a6 6 0 0 1 0 12z" fill="currentColor" />
      </svg>
      <span>{theme === "dark" ? "Light" : "Dark"}</span>
    </button>
  );
}
