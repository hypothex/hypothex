// ui/test/styles/kept.test.ts — the kept pages use only v5 tokens
import { describe, expect, test } from "bun:test";
import { LAUNCH_CSS } from "../../src/launch/styles";

const read = (rel: string): Promise<string> => Bun.file(new URL(rel, import.meta.url)).text();
const V4 = /var\(--(paper|paper-2|rule|rule-2|serif|sans|agent|human|best|best-wash|best-edge)\)/;

describe("kept pages", () => {
  test("launch dialog, editor, examples, palette and auth CSS use no v4 token", async () => {
    for (const css of [LAUNCH_CSS, await read("../../src/editor/editor.css"), await read("../../src/pages/examples.css"), await read("../../src/shell/kept.css")]) {
      expect(css.match(V4)).toBeNull();
    }
  });

  test("palette and toast rules live with the palette", async () => {
    const css = await read("../../src/shell/kept.css");
    for (const selector of [".pal {", ".pal-box {", ".pal-in {", ".toast {", ".toast.on {", ".auth-gate {"]) expect(css).toContain(selector);
  });

  test("base.css no longer carries palette or toast rules", async () => {
    const css = await read("../../src/styles/base.css");
    expect(css).not.toMatch(/^\.(pal|toast)\b/m);
  });
});
