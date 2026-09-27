/**
 * Real Vega (no vega-embed mock): a spec that names external resources in nested places
 * reaches the page's loader, and `DENY_LOADER` refuses every one, so nothing is fetched.
 * The spy loader test is the control: it shows the same spec does ask for all three URLs.
 */
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import { type Loader, None, parse, View } from "vega";
import { compile, type TopLevelSpec } from "vega-lite";
import { buildSpec, DENY_LOADER, themeConfig, TOKEN_FALLBACK } from "../../src/panels/VegaLite";

type Obj = Record<string, unknown>;

const EVIL = "https://evil.example";
// Root data is replaced by the panel rows; the three URLs sit where `buildSpec` does not look.
const SPEC: Obj = {
  data: { url: `${EVIL}/root.csv` },
  transform: [
    { lookup: "a", from: { data: { url: `${EVIL}/lookup.csv` }, key: "a", fields: ["b"] } },
  ],
  layer: [
    { mark: "point", encoding: { x: { field: "a", type: "quantitative" } } },
    {
      data: { url: `${EVIL}/layer.csv` },
      mark: "rule",
      encoding: { x: { field: "a", type: "quantitative" } },
    },
    {
      mark: { type: "image", width: 10, height: 10 },
      encoding: {
        x: { field: "a", type: "quantitative" },
        url: { value: `${EVIL}/pixel.png` },
      },
    },
  ],
};
const WANTED = [`${EVIL}/lookup.csv`, `${EVIL}/layer.csv`, `${EVIL}/pixel.png`];

const realFetch = globalThis.fetch;
const realImage = globalThis.Image;
const fetched = mock(async (_input: RequestInfo | URL) => new Response("a,b\n1,2\n"));
let images: string[] = [];

beforeEach(() => {
  fetched.mockClear();
  images = [];
  globalThis.fetch = fetched as unknown as typeof fetch;
  // Records every image Vega starts to download, then reports it loaded.
  globalThis.Image = class {
    crossOrigin: string | null = null;
    complete = false;
    width = 10;
    height = 10;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src(url: string) {
      images.push(url);
      setTimeout(() => {
        this.complete = true;
        this.onload?.();
      }, 0);
    }
  } as unknown as typeof Image;
});
afterEach(() => {
  globalThis.fetch = realFetch;
  globalThis.Image = realImage;
  document.body.innerHTML = "";
});

/** Compile and render the panel's spec with real Vega; returns every URI the loader saw. */
async function renderWith(inner: Loader): Promise<string[]> {
  const asked: string[] = [];
  const loader: Loader = {
    load: (uri, options) => {
      asked.push(uri);
      return inner.load(uri, options);
    },
    sanitize: (uri, options) => {
      asked.push(uri);
      return inner.sanitize(uri, options);
    },
    http: (uri, options) => inner.http(uri, options),
    file: (name) => inner.file(name),
  };
  const full = buildSpec(SPEC, [{ a: 1 }], themeConfig(TOKEN_FALLBACK.light, "light"));
  const el = document.createElement("div");
  document.body.append(el);
  const view = new View(parse(compile(full as unknown as TopLevelSpec).spec), {
    loader,
    renderer: "svg",
    container: el,
    logLevel: None,
  });
  await view.runAsync();
  await new Promise((r) => setTimeout(r, 20)); // image loads start after the first render
  view.finalize();
  return asked;
}

describe("VegaLite resources with real Vega", () => {
  test("control: an allowing loader is asked for the nested data and the image", async () => {
    const allow: Loader = {
      load: async () => "a,b\n1,2\n",
      sanitize: async (uri) => ({ href: uri }),
      http: async () => "",
      file: async () => "",
    };
    const asked = await renderWith(allow);
    for (const url of WANTED) expect(asked).toContain(url);
    expect(asked).not.toContain(`${EVIL}/root.csv`); // buildSpec replaced the root data
    expect(images).toEqual([`${EVIL}/pixel.png`]);
  });

  test("DENY_LOADER: the same URLs are refused; no fetch, no image download", async () => {
    const asked = await renderWith(DENY_LOADER);
    for (const url of WANTED) expect(asked).toContain(url);
    expect(fetched).not.toHaveBeenCalled();
    expect(images).toEqual([]);
  });
});
