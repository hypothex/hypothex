import { describe, expect, test } from "bun:test";
import { PAGES_CSS } from "../../src/pages/components/styles";

const read = (rel: string): Promise<string> => Bun.file(new URL(rel, import.meta.url)).text();

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

describe("leaderboard rows (UI-F4)", () => {
  test("name and plot tracks both flex, the name has a floor", async () => {
    const frow = rule(await read("../../src/panels/panels.css"), ".frow");
    expect(frow).toContain("grid-template-columns: minmax(140px, 1fr) 118px minmax(160px, 3fr) 84px 128px;");
    expect(frow).not.toMatch(/minmax\(240px, 600px\)/);
  });

  test("rows grow with wrapped meta instead of overlapping the next row", async () => {
    const css = await read("../../src/panels/panels.css");
    const frow = rule(css, ".frow");
    expect(frow).toContain("min-height: 105px;");
    expect(frow).not.toMatch(/(^|[^-])height: 105px/);
    expect(rule(css, ".frow.head")).toContain("min-height: 0;");
    expect(rule(css, ".frow.axisrow")).toContain("min-height: 0;");
  });

  test("a narrow card drops the f1 column and puts vs best under the plot", async () => {
    const css = await read("../../src/panels/panels.css");
    expect(rule(css, ".forest")).toContain("container-type: inline-size;");
    const at = css.indexOf("@container (max-width: 760px)");
    expect(at).toBeGreaterThan(0);
    const block = css.slice(at, css.indexOf("\n}", at));
    expect(block).toContain("grid-template-columns: minmax(120px, 1fr) 96px minmax(140px, 2fr);");
    expect(block).toMatch(/\.frow \.f1[^{]*\{ display: none; \}/);
    expect(block).toContain(".frow .vd { grid-column: 3;");
  });
});

describe("command palette rows (UI-F8)", () => {
  test("the title keeps one line; the subtitle takes the rest and ends in an ellipsis", async () => {
    const css = await read("../../src/styles/base.css");
    expect(rule(css, ".pal-list li.it")).toContain("grid-template-columns: max-content minmax(0, 1fr);");
    const small = rule(css, ".pal-list li.it small");
    for (const d of ["white-space: nowrap;", "overflow: hidden;", "text-overflow: ellipsis;", "text-align: right;"]) {
      expect(small).toContain(d);
    }
  });
});
