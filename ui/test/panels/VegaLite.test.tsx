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
  isMultiView,
  isRowFacet,
  PROBE_W,
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
    expect(out.$schema).toBe("https://vega.github.io/schema/vega-lite/v6.json");
    expect((spec.data as Obj).values).toEqual([]);
  });

  test("multi-view specs keep their own width; url and name are dropped", () => {
    const out = buildSpec({ hconcat: [], data: { url: "x.csv", name: "d" } }, ROWS, theme);
    expect("width" in out).toBe(false);
    expect(out.data).toEqual({ values: ROWS });
  });

  test("single views fit the width only; facet encodings are multi-view", () => {
    expect(buildSpec(SPEC, ROWS, theme).autosize).toEqual({ type: "fit-x", contains: "padding" });
    const rowSpec = { mark: "line", encoding: { row: { field: "run_id" }, x: { field: "step" } } };
    expect(isMultiView(rowSpec)).toBe(true);
    const out = buildSpec(rowSpec, ROWS, theme);
    expect("width" in out).toBe(false);
    expect("autosize" in out).toBe(false);
  });

  test("a row facet takes the given cell width; other layouts ignore it", () => {
    const rowSpec = { mark: "line", encoding: { row: { field: "run_id" } } };
    expect(isRowFacet(rowSpec)).toBe(true);
    expect(buildSpec(rowSpec, ROWS, theme, 321).width).toBe(321);
    const op = { facet: { row: { field: "g" } }, spec: { mark: "bar" } };
    expect(isRowFacet(op)).toBe(true);
    expect((buildSpec(op, ROWS, theme, 300).spec as Obj).width).toBe(300);
    expect(isRowFacet({ ...rowSpec, width: 100 })).toBe(false);
    expect(isRowFacet({ mark: "bar", encoding: { row: {}, column: {} } })).toBe(false);
    expect(isRowFacet({ facet: { row: {} }, columns: 2, spec: {} })).toBe(false);
    expect(isRowFacet(SPEC)).toBe(false);
    expect("width" in buildSpec({ hconcat: [] }, ROWS, theme, 300)).toBe(false);
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

describe("row facet fitting", () => {
  test("the first embed probes a fixed cell width", async () => {
    const spec = { mark: "line", encoding: { row: { field: "run_id" } } };
    render(<VegaLitePanel result={{ type: "vega_lite", title: "t", rows: ROWS, meta: { spec } }} />);
    await waitFor(() => expect(embedMock).toHaveBeenCalled());
    expect((embedMock.mock.calls[0]?.[1] as Obj).width).toBe(PROBE_W);
  });
});

describe("responsive horizontal legends", () => {
  const spec = {
    mark: "bar",
    encoding: { color: { field: "category", type: "nominal", legend: { orient: "bottom", columns: 3 } } },
  };
  const columnsOf = (value: Obj): number => (((value.encoding as Obj).color as Obj).legend as Obj).columns as number;

  test("an overflowing legend drops columns, while wide and explicit-width charts preserve them", async () => {
    const original = HTMLElement.prototype.getBoundingClientRect;
    try {
      embedMock.mockImplementation(async (el, value) => {
        const columns = columnsOf(value as Obj);
        const legend = document.createElementNS("http://www.w3.org/2000/svg", "g");
        legend.classList.add("role-legend");
        legend.getBoundingClientRect = () => ({ width: columns * 145 }) as DOMRect;
        el.replaceChildren(legend);
        return { finalize, spec: value, view: {} };
      });
      for (const [width, input, expected] of [
        [320, spec, 2], [640, spec, 3], [100, spec, 1],
        [320, { ...spec, width: 600 }, 3],
        [320, { ...spec, encoding: { color: { ...spec.encoding.color,
          legend: { orient: "right", columns: 3 } } } }, 3],
        [320, { ...spec, encoding: { ...spec.encoding, row: { field: "run_id" } } }, 3],
      ] as const) {
        HTMLElement.prototype.getBoundingClientRect = () => ({ width }) as DOMRect;
        embedMock.mockClear();
        const { unmount } = render(<VegaLitePanel result={vega({ spec: input })} />);
        await waitFor(() => expect(columnsOf(lastSpec())).toBe(expected));
        expect(spec.encoding.color.legend.columns).toBe(3);
        unmount();
      }
    } finally {
      HTMLElement.prototype.getBoundingClientRect = original;
      embedMock.mockImplementation(async (_el, value) => ({ finalize, spec: value, view: {} }));
    }
  });

  test("widening a mounted panel restores requested columns; fitting has bounded retries", async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect;
    const originalObserver = globalThis.ResizeObserver;
    const callbacks: ResizeObserverCallback[] = [];
    let width = 320;
    globalThis.ResizeObserver = class {
      constructor(callback: ResizeObserverCallback) { callbacks.push(callback); }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as typeof ResizeObserver;
    HTMLElement.prototype.getBoundingClientRect = () => ({ width }) as DOMRect;
    embedMock.mockImplementation(async (el, value) => {
      const legend = document.createElementNS("http://www.w3.org/2000/svg", "g");
      legend.classList.add("role-legend");
      legend.getBoundingClientRect = () => ({ width: columnsOf(value as Obj) * 145 }) as DOMRect;
      el.replaceChildren(legend);
      return { finalize, spec: value, view: {} };
    });
    try {
      const mounted = render(<VegaLitePanel result={vega({ spec })} />);
      await waitFor(() => expect(columnsOf(lastSpec())).toBe(2));
      act(() => {
        width = 640;
        callbacks.forEach((callback) => callback([], {} as ResizeObserver));
      });
      await waitFor(() => expect(columnsOf(lastSpec())).toBe(3));
      mounted.unmount();
      embedMock.mockClear();
      const extreme = { ...spec, encoding: { color: { ...spec.encoding.color,
        legend: { orient: "bottom", columns: 10000 } } } };
      render(<VegaLitePanel result={vega({ spec: extreme })} />);
      await waitFor(() => expect(columnsOf(lastSpec())).toBe(1));
      // One initial unmeasured embed, then at most four measured draws.
      expect(embedMock.mock.calls.length).toBeLessThanOrEqual(5);
    } finally {
      cleanup();
      HTMLElement.prototype.getBoundingClientRect = originalRect;
      globalThis.ResizeObserver = originalObserver;
      embedMock.mockImplementation(async (_el, value) => ({ finalize, spec: value, view: {} }));
    }
  });

  test("legend fitting accounts for offsets inside a panel, not just legend width", async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = () => ({ width: 380, left: 100, right: 480 }) as DOMRect;
    try {
      for (const offset of [20, -5]) {
        embedMock.mockImplementation(async (el, value) => {
          const columns = columnsOf(value as Obj);
          const width = columns === 3 ? 365 : 240;
          const left = 100 + (columns === 3 ? offset : 20);
          const legend = document.createElementNS("http://www.w3.org/2000/svg", "g");
          legend.classList.add("role-legend");
          legend.getBoundingClientRect = () => ({ width, left, right: left + width }) as DOMRect;
          el.replaceChildren(legend);
          return { finalize, spec: value, view: {} };
        });
        const { unmount } = render(<VegaLitePanel result={vega({ spec })} />);
        await waitFor(() => expect(columnsOf(lastSpec())).toBe(2));
        unmount();
      }
    } finally {
      HTMLElement.prototype.getBoundingClientRect = originalRect;
      embedMock.mockImplementation(async (_el, value) => ({ finalize, spec: value, view: {} }));
    }
  });

  test("height changes from an embed error do not start another embed", async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect;
    const originalObserver = globalThis.ResizeObserver;
    const callbacks: ResizeObserverCallback[] = [];
    let height = 200;
    globalThis.ResizeObserver = class {
      constructor(callback: ResizeObserverCallback) { callbacks.push(callback); }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as typeof ResizeObserver;
    HTMLElement.prototype.getBoundingClientRect = () => ({ width: 380, height }) as DOMRect;
    embedMock.mockImplementation(async () => { throw new Error("bad spec"); });
    try {
      render(<VegaLitePanel result={vega({ spec })} />);
      expect((await screen.findByRole("alert")).textContent).toBe("Vega-Lite: bad spec");
      const embeds = embedMock.mock.calls.length;
      await act(async () => {
        for (height = 240; height < 300; height += 10) {
          callbacks.forEach((callback) => callback([], {} as ResizeObserver));
        }
      });
      expect(embedMock.mock.calls.length).toBe(embeds);
      expect(screen.getByRole("alert").textContent).toBe("Vega-Lite: bad spec");
    } finally {
      cleanup();
      HTMLElement.prototype.getBoundingClientRect = originalRect;
      globalThis.ResizeObserver = originalObserver;
      embedMock.mockImplementation(async (_el, value) => ({ finalize, spec: value, view: {} }));
    }
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

  test("readTokens takes the category palette from the --cat-N tokens", () => {
    const t = readTokens("light", (n) => (n === "--cat-2" ? " #123456 " : ""));
    expect(t.cat).toEqual(["#2a78d6", "#123456", "#b8447e", "#eda100", "#4a3aa7"]);
    const cfg = themeConfig(t, "light");
    expect((cfg.range as Obj).category).toEqual(t.cat);
  });

  test("fonts and sizes match the app charts; bars use the palette, not ink", () => {
    const t = TOKEN_FALLBACK.dark;
    const cfg = themeConfig(t, "dark");
    const axis = cfg.axis as Obj;
    expect([axis.labelFont, axis.titleFont, (cfg.legend as Obj).labelFont]).toEqual([t.sans, t.sans, t.sans]);
    expect([axis.labelFontSize, axis.titleFontSize]).toEqual([11, 12]);
    expect((cfg.bar as Obj).color).toBe("#4a90e8");
    expect((cfg.bar as Obj).color).not.toBe(t.ink);
    // Geist's browser SVG text bounds are taller than the fontSize used by Vega layout.
    expect((cfg.legend as Obj).rowPadding).toBe(6);
    const custom = buildSpec({ ...SPEC, config: { legend: { rowPadding: 12 } } }, ROWS, cfg);
    expect(((custom.config as Obj).legend as Obj).rowPadding).toBe(12);
  });

  test("the palette tokens in palette.css match the fallback arrays", async () => {
    const css = await Bun.file(new URL("../../src/styles/palette.css", import.meta.url)).text();
    const [light, dark] = css.split('[data-theme="dark"]');
    TOKEN_FALLBACK.light.cat.forEach((c, i) => expect(light).toContain(`--cat-${i + 1}: ${c};`));
    TOKEN_FALLBACK.dark.cat.forEach((c, i) => expect(dark).toContain(`--cat-${i + 1}: ${c};`));
  });

  test("the theme never overrides the spec's legend labels or its own config", () => {
    const spec = {
      mark: "bar",
      encoding: {
        color: { field: "over", type: "nominal", legend: { labelExpr: "datum.value ? 'over' : 'ok'" } },
      },
      config: { bar: { color: "#abcdef" } },
    };
    const out = buildSpec(spec, ROWS, themeConfig(TOKEN_FALLBACK.light, "light"));
    expect(out.encoding).toEqual(spec.encoding);
    expect(((out.config as Obj).bar as Obj).color).toBe("#abcdef");
    expect(((out.config as Obj).legend as Obj).labelExpr).toBeUndefined();
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
