import { describe, expect, test } from "bun:test";

const read = (rel: string): Promise<string> => Bun.file(new URL(rel, import.meta.url)).text();

/** The `:root { ... }` and `[data-theme="dark"] { ... }` blocks of the approved mockup. */
async function mockupTokens(): Promise<string> {
  const html = await read("../../../docs/mockups/ui-v4/index.html");
  const start = html.indexOf(":root {");
  const darkStart = html.indexOf('[data-theme="dark"] {');
  const end = html.indexOf("}", darkStart) + 1;
  if (start < 0 || darkStart < start) throw new Error("token blocks not found in mockup");
  return html.slice(start, end);
}

describe("tokens.css", () => {
  test("is a verbatim copy of the mockup tokens (light and dark)", async () => {
    const tokens = await read("../../src/styles/tokens.css");
    const expected = await mockupTokens();
    expect(tokens).toContain(expected);
    expect(tokens).toContain("--paper: #F6F7F3;");
    expect(tokens).toContain("--best: #1FA282;");
  });
});

describe("base.css", () => {
  test("self-hosts the three mockup fonts under their token names", async () => {
    const css = await read("../../src/styles/base.css");
    for (const family of ['"Geist"', '"Geist Mono"', '"Newsreader"']) {
      expect(css).toContain(`font-family: ${family};`);
    }
    expect(css).not.toContain("fonts.googleapis.com");
  });

  test("carries the shared chrome, palette and figure rules", async () => {
    const css = await read("../../src/styles/base.css");
    for (const sel of [".bar {", ".bar-in {", ".brand {", ".tabs a[aria-current=\"page\"]", ".find {",
      ".theme {", "main {", "h1.finding {", ".stats {", ".fig-h {", ".btn {", ".tbl {", ".pal {",
      ".pal-list li.it[aria-selected=\"true\"]", ".toast {", ".tip {"]) {
      expect(css).toContain(sel);
    }
  });

  test("table columns keep a gap so adjacent headers and cells never touch", async () => {
    const css = await read("../../src/styles/base.css");
    expect(css).toContain(".tbl th + th, .tbl td + td { padding-left: 20px; }");
  });
});
