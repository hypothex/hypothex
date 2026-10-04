import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { Notes } from "../../src/pages/components/Notes";
import { RUN_SVM } from "./fixtures";
import { mockApi, renderWithClient, restoreFetch } from "./helpers";

/** Fake layout: a clamped `p.clip` is `clipped` px taller than its box. */
function fakeLayout(clipped: number): () => void {
  const proto = HTMLElement.prototype;
  const saved = {
    scroll: Object.getOwnPropertyDescriptor(proto, "scrollHeight"),
    client: Object.getOwnPropertyDescriptor(proto, "clientHeight"),
  };
  Object.defineProperty(proto, "clientHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains("clip") ? 72 : 0;
    },
  });
  Object.defineProperty(proto, "scrollHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains("clip") ? 72 + clipped : 0;
    },
  });
  return () => {
    for (const [key, d] of [["scrollHeight", saved.scroll], ["clientHeight", saved.client]] as const) {
      if (d) Object.defineProperty(proto, key, d);
      else delete (proto as unknown as Record<string, unknown>)[key];
    }
  };
}

let restoreLayout: (() => void) | null = null;

afterEach(() => {
  cleanup();
  restoreFetch();
  restoreLayout?.();
  restoreLayout = null;
});

const NOTE_220 = `## 2026-10-03T03:03:06+00:00 — human\n\n${"SVM is the best so far. ".repeat(9).slice(0, 220)}\n`;
const NOTE_400 = `## 2026-10-03T03:03:06+00:00 — human\n\n${"x".repeat(400)}\n`;

describe("Notes More", () => {
  test("shows More when the one note is clipped, even under 280 chars", () => {
    restoreLayout = fakeLayout(48);
    mockApi({});
    renderWithClient(<Notes runId={RUN_SVM} notes={NOTE_220} />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("button", { name: "Less" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Less" }));
    expect(screen.getByRole("button", { name: "More" })).toBeTruthy();
  });

  test("no More when the one note fits, even over 280 chars", () => {
    restoreLayout = fakeLayout(0);
    mockApi({});
    renderWithClient(<Notes runId={RUN_SVM} notes={NOTE_400} />);
    expect(screen.queryByRole("button", { name: "More" }) === null).toBe(true);
  });
});
