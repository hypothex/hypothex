import { describe, expect, test } from "bun:test";
import { PAGES_CSS } from "../../src/pages/components/styles";

/** Declarations of the first rule whose selector is exactly `selector`. */
function rule(css: string, selector: string): string {
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule for ${selector}`);
  return css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at)).trim();
}

describe("run-top action error (UI-F2)", () => {
  test("the error adds no width to the actions column, so the headline keeps its width", () => {
    const err = rule(PAGES_CSS, ".page .run-top .err");
    expect(err).toContain("width: 0;");
    expect(err).toContain("min-width: 100%;");
    expect(err).toContain("overflow-wrap: anywhere;");
  });
});
