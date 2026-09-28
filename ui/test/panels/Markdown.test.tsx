import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { MarkdownPanel, parseBlocks, safeHref } from "../../src/panels/Markdown";

afterEach(cleanup);

const md = (text: string): PanelResult => ({
  type: "markdown",
  title: "Note",
  rows: [],
  meta: { text },
});

describe("parseBlocks", () => {
  test("splits paragraphs, headings, lists, code and rules", () => {
    const src = "# Title\nline one\nline two\n\n- a\n- b\n\n1. x\n2. y\n\n```\ncode\n```\n---";
    expect(parseBlocks(src)).toEqual([
      { kind: "h", level: 1, text: "Title" },
      { kind: "p", lines: ["line one", "line two"] },
      { kind: "ul", items: ["a", "b"] },
      { kind: "ol", items: ["x", "y"] },
      { kind: "code", text: "code" },
      { kind: "hr" },
    ]);
  });

  test("an unclosed fence runs to the end", () => {
    expect(parseBlocks("```\na\nb")).toEqual([{ kind: "code", text: "a\nb" }]);
  });
});

describe("safeHref", () => {
  test("keeps web, mail, relative and anchor links", () => {
    expect(safeHref("https://example.com/x")).toBe("https://example.com/x");
    expect(safeHref("mailto:a@b.c")).toBe("mailto:a@b.c");
    expect(safeHref("/r/abc")).toBe("/r/abc");
    expect(safeHref("#sec")).toBe("#sec");
  });

  test("drops script, data and protocol-relative links", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("JavaScript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<b>x</b>")).toBeNull();
    expect(safeHref("//evil.example")).toBeNull();
  });
});

describe("MarkdownPanel", () => {
  test("renders the mockup note: bold value and two lines", () => {
    const text =
      "Critic gain is largest on 5+ step targets: **+0.05**.\nNext: mcts-256+critic, 3 seeds.";
    const { container } = render(<MarkdownPanel result={md(text)} />);
    expect(container.querySelector("b")?.textContent).toBe("+0.05");
    const p = container.querySelector("p");
    expect(p?.querySelectorAll("br").length).toBe(1);
    expect(p?.textContent).toBe(
      "Critic gain is largest on 5+ step targets: +0.05.Next: mcts-256+critic, 3 seeds.",
    );
  });

  test("inline code, italic and lists render as elements", () => {
    const { container } = render(<MarkdownPanel result={md("use `hx view` *now*\n\n- a\n- b")} />);
    expect(container.querySelector("code")?.textContent).toBe("hx view");
    expect(container.querySelector("i")?.textContent).toBe("now");
    expect(container.querySelectorAll("ul li").length).toBe(2);
  });

  test("raw HTML shows as text and never becomes elements", () => {
    const text = '<script>alert(1)</script>\n<img src=x onerror="alert(1)">';
    const { container } = render(<MarkdownPanel result={md(text)} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  test("code fences keep HTML as literal text", () => {
    const { container } = render(<MarkdownPanel result={md("```\n<b>x</b>\n```")} />);
    expect(container.querySelector("pre code")?.textContent).toBe("<b>x</b>");
    expect(container.querySelector("b")).toBeNull();
  });

  test("links: external opens a new tab, relative stays, unsafe loses its anchor", () => {
    const text = "[docs](https://example.com) [run](/r/abc) [bad](javascript:alert)";
    const { container } = render(<MarkdownPanel result={md(text)} />);
    const docs = screen.getByRole("link", { name: "docs" });
    expect(docs.getAttribute("href")).toBe("https://example.com");
    expect(docs.getAttribute("target")).toBe("_blank");
    expect(docs.getAttribute("rel")).toBe("noreferrer noopener");
    expect(screen.getByRole("link", { name: "run" }).getAttribute("target")).toBeNull();
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
    expect(container.textContent).toContain("bad");
    for (const a of container.querySelectorAll("a")) {
      expect(a.getAttribute("href") ?? "").not.toContain("javascript");
    }
  });

  test("missing text says so", () => {
    render(<MarkdownPanel result={{ type: "markdown", title: "Note", rows: [], meta: {} }} />);
    expect(screen.getByText("No text")).toBeTruthy();
  });
});
