import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { setTheme } from "../../src/shell/ThemeToggle";
import type { PanelResult } from "../../src/panels/index";

type Obj = Record<string, unknown>;

const finalize = mock(() => {});
const embedMock = mock(async (_el: HTMLElement, spec: unknown, _opts: unknown) => ({
  finalize,
  spec,
  view: {},
}));
mock.module("vega-embed", () => ({ default: embedMock }));

const {
  buildSpec,
  DENY_LOADER,
  deepMerge,
  EXTERNAL_DISABLED,
  readTokens,
  themeConfig,
  TOKEN_FALLBACK,
  VegaLitePanel,
} = await import("../../src/panels/VegaLite");

beforeEach(() => {
  embedMock.mockClear();
  finalize.mockClear();
  delete document.documentElement.dataset.theme;
});
afterEach(cleanup);

const SPEC = {
  mark: "point",
  encoding: { x: { field: "a", type: "quantitative" } },
  data: { values: [] },
};
const ROWS = [{ a: 1 }, { a: 2 }];
const vega = (meta: Obj, rows: Obj[] = ROWS): PanelResult => ({
  type: "vega_lite",
  title: "Solved by depth",
  rows,
  meta,
});
const lastSpec = () => embedMock.mock.calls.at(-1)?.[1] as Obj;
const axisOf = (spec: Obj) => (spec.config as Obj).axis as Obj;

describe("deepMerge", () => {
  test("merges nested objects; arrays and scalars replace", () => {
    expect(
      deepMerge(
        { axis: { labelColor: "a", labelFontSize: 11 }, range: { category: ["x"] } },
        { axis: { labelFontSize: 20 }, range: { category: ["y", "z"] } },
      ),
    ).toEqual({ axis: { labelColor: "a", labelFontSize: 20 }, range: { category: ["y", "z"] } });
  });
});

describe("buildSpec", () => {
  const theme = themeConfig(TOKEN_FALLBACK.light, "light");

  test("injects copies of rows, keeps user config on top, fills container width", () => {
    const spec = { ...SPEC, config: { axis: { labelFontSize: 20 } } };
    const out = buildSpec(spec, ROWS, theme);
    const values = (out.data as Obj).values as Obj[];
    expect(values).toEqual(ROWS);
    expect(values[0]).not.toBe(ROWS[0]);
    expect(axisOf(out).labelFontSize).toBe(20);
    expect(axisOf(out).labelColor).toBe("#767C87");
    expect(out.width).toBe("container");
    expect(out.$schema).toBe("https://vega.github.io/schema/vega-lite/v5.json");
    expect((spec.data as Obj).values).toEqual([]);
  });

  test("multi-view specs keep their own width; url and name are dropped", () => {
    const out = buildSpec({ hconcat: [], data: { url: "x.csv", name: "d" } }, ROWS, theme);
    expect("width" in out).toBe(false);
    expect(out.data).toEqual({ values: ROWS });
  });

  test("usermeta is dropped, so a spec cannot set its own embed options", () => {
    const spec = {
      ...SPEC,
      usermeta: { embedOptions: { actions: true, config: "https://evil.example/c.json" } },
    };
    const out = buildSpec(spec, ROWS, theme);
    expect("usermeta" in out).toBe(false);
    expect("usermeta" in spec).toBe(true);
  });
});

describe("DENY_LOADER", () => {
  test("refuses every kind of resource", async () => {
    const url = "https://evil.example/x.csv";
    const attempts = [
      DENY_LOADER.load(url),
      DENY_LOADER.sanitize(url, { context: "image" }),
      DENY_LOADER.sanitize(url, { context: "href" }),
      DENY_LOADER.http(url, {}),
      DENY_LOADER.file("/etc/passwd"),
    ];
    const results = await Promise.allSettled(attempts);
    expect(results.map((r) => r.status)).toEqual(Array(5).fill("rejected"));
    for (const r of results) {
      expect((r as PromiseRejectedResult).reason.message).toBe(EXTERNAL_DISABLED);
    }
  });
});

describe("tokens and theme", () => {
  test("readTokens falls back per theme and trims values it can read", () => {
    expect(readTokens("dark", () => "")).toEqual(TOKEN_FALLBACK.dark);
    const t = readTokens("light", (n) => (n === "--ink" ? " #101010 " : ""));
    expect(t.ink).toBe("#101010");
    expect(t.ink3).toBe("#767C87");
  });

  test("themeConfig uses the mode's colours and series order", () => {
    const dark = themeConfig(TOKEN_FALLBACK.dark, "dark");
    expect((dark.axis as Obj).labelColor).toBe("#7C8490");
    expect(((dark.range as Obj).category as string[])[0]).toBe("#4a90e8");
    expect((dark.range as Obj).ramp).toEqual(["#1A1F27", "#1FA282"]);
  });
});

describe("VegaLitePanel", () => {
  test("embeds the spec with rows and the light theme", async () => {
    render(<VegaLitePanel result={vega({ spec: SPEC })} />);
    await waitFor(() => expect(embedMock).toHaveBeenCalledTimes(1));
    const [el, spec, opts] = embedMock.mock.calls[0];
    expect(el).toBe(screen.getByTestId("vega"));
    expect((spec as Obj).data).toEqual({ values: ROWS });
    expect(opts).toEqual({ actions: false, renderer: "svg", loader: DENY_LOADER });
    expect((opts as { loader: unknown }).loader).toBe(DENY_LOADER);
    expect(axisOf(spec as Obj).labelColor).toBe("#767C87");
  });

  test("re-embeds with dark colours when the theme flips, and cleans up", async () => {
    const { unmount } = render(<VegaLitePanel result={vega({ spec: SPEC })} />);
    await waitFor(() => expect(embedMock).toHaveBeenCalledTimes(1));
    act(() => {
      setTheme("dark");
    });
    await waitFor(() => expect(embedMock).toHaveBeenCalledTimes(2));
    expect(axisOf(lastSpec()).labelColor).toBe("#7C8490");
    expect(finalize).toHaveBeenCalledTimes(1);
    unmount();
    expect(finalize).toHaveBeenCalledTimes(2);
  });

  test("shows the embed error", async () => {
    embedMock.mockImplementationOnce(async () => {
      throw new Error("bad spec");
    });
    render(<VegaLitePanel result={vega({ spec: SPEC })} />);
    expect((await screen.findByRole("alert")).textContent).toBe("Vega-Lite: bad spec");
  });

  test("missing spec says so and never embeds", () => {
    render(<VegaLitePanel result={vega({})} />);
    expect(screen.getByRole("alert").textContent).toBe("No Vega-Lite spec");
    expect(embedMock).not.toHaveBeenCalled();
  });
});
