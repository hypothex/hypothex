import { describe, expect, test } from "bun:test";
import { fileURLToPath } from "node:url";

const read = (rel: string): Promise<string> => Bun.file(new URL(rel, import.meta.url)).text();

/** `--name: value` declarations of every block whose selector is exactly `selector`, merged in order. */
function declarations(css: string, selector: string): Map<string, string> {
  const out = new Map<string, string>();
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const block of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if ((block[1] ?? "").trim() !== selector) continue;
    for (const d of (block[2] ?? "").matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      out.set(d[1] ?? "", (d[2] ?? "").trim().toLowerCase());
    }
  }
  return out;
}

async function ours(selector: string): Promise<Map<string, string>> {
  const css = (await read("../../src/styles/tokens.css")) + (await read("../../src/styles/palette.css"));
  return declarations(css, selector);
}

async function mockup(selector: string): Promise<Map<string, string>> {
  const html = await read("../../../docs/mockups/ui-v5/index.html");
  const style = html.slice(html.indexOf("<style>") + 7, html.indexOf("</style>"));
  return declarations(style, selector);
}

describe("tokens.css + palette.css", () => {
  for (const selector of [":root", '[data-theme="dark"]']) {
    test(`carries every token of the v5 mockup's ${selector} block with its value`, async () => {
      const want = await mockup(selector);
      const have = await ours(selector);
      expect(want.size).toBeGreaterThan(15);
      for (const [name, value] of want) expect([name, have.get(name)]).toEqual([name, value]);
    });
  }

  test("identity slots c1..c8 and the neutral c0 are the spec's validated hexes", async () => {
    const light = await ours(":root");
    const dark = await ours('[data-theme="dark"]');
    const slots = (m: Map<string, string>) => [1, 2, 3, 4, 5, 6, 7, 8, 0].map((i) => m.get(`--c${i}`));
    expect(slots(light)).toEqual([
      "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948", "#c4c4cc",
    ]);
    expect(slots(dark)).toEqual([
      "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767", "#4a4a52",
    ]);
  });

  test("status and surface tokens follow spec section 7", async () => {
    const light = await ours(":root");
    const dark = await ours('[data-theme="dark"]');
    expect(["--bg", "--panel", "--panel-2", "--hover", "--line", "--ink", "--ink-2", "--ink-3", "--focus"].map((n) => light.get(n)))
      .toEqual(["#f7f7f8", "#ffffff", "#fafafa", "#f1f1f3", "#e7e7ea", "#18181b", "#52525b", "#8b8b94", "#2a78d6"]);
    expect(["--ok", "--ok-wash", "--fail", "--warn", "--run"].map((n) => light.get(n)))
      .toEqual(["#138a43", "#e9f6ee", "#d03b3b", "#b97800", "#2a78d6"]);
    expect(["--bg", "--panel", "--line", "--ink", "--ink-2", "--ink-3"].map((n) => dark.get(n)))
      .toEqual(["#111113", "#18181b", "#27272a", "#ededef", "#a1a1aa", "#71717a"]);
    expect([light.get("--r-panel"), light.get("--r-ctl")]).toEqual(["10px", "7px"]);
  });

  test("v4 token names still used by kept modules point at v5 tokens", async () => {
    const light = await ours(":root");
    for (const name of ["--paper", "--paper-2", "--rule", "--rule-2", "--best", "--agent", "--human", "--sans"]) {
      expect([name, light.get(name)?.startsWith("var(--")]).toEqual([name, true]);
    }
  });
});

describe("fonts", () => {
  test("base.css self-hosts Geist and Geist Mono and sets the 13 px tabular base", async () => {
    const css = await read("../../src/styles/base.css");
    for (const family of ['"Geist"', '"Geist Mono"']) expect(css).toContain(`font-family: ${family};`);
    expect(css).not.toContain("fonts.googleapis.com");
    expect(css).toMatch(/body \{[^}]*font: 13px\/1\.5 var\(--font\);[^}]*font-variant-numeric: tabular-nums;/);
  });

  test("no serif anywhere: no Newsreader, no --serif, no Georgia, no dependency", async () => {
    const src = fileURLToPath(new URL("../../src", import.meta.url));
    const offenders: string[] = [];
    for await (const path of new Bun.Glob("**/*.{css,ts,tsx}").scan({ cwd: src })) {
      const text = await Bun.file(`${src}/${path}`).text();
      if (/Newsreader|--serif|Georgia/.test(text)) offenders.push(path);
    }
    expect(offenders).toEqual([]);
    expect(await read("../../package.json")).not.toContain("newsreader");
  });
});
