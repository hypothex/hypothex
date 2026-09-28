/**
 * Vega-Lite panel: renders `meta.spec` with vega-embed, injecting the panel rows as
 * `data.values` and a Hypothex theme built from the current design tokens. Re-embeds when
 * the colour mode changes (`useTheme` from the shell).
 *
 * A view spec is untrusted input (anyone with repo access writes one), so the panel never
 * lets Vega reach the network: every resource goes through `DENY_LOADER`, which refuses it.
 * That covers nested `data.url` in layers and concats, `lookup` sources, image marks and
 * `href` links, whatever the server-side validation missed.
 */
import type { Loader } from "vega";
import embed, { type EmbedOptions, type Result, type VisualizationSpec } from "vega-embed";
import { type CSSProperties, useEffect, useRef, useState } from "react";
import { type Theme, useTheme } from "../shell/ThemeToggle";
import { FS } from "../charts/Scale";
import { SERIES_DARK, SERIES_LIGHT } from "./Distribution";
import type { PanelResult } from "./index";

type Obj = Record<string, unknown>;

/** Design tokens the theme needs. */
export type Tokens = {
  paper: string;
  paper2: string;
  ink: string;
  ink2: string;
  ink3: string;
  rule: string;
  rule2: string;
  best: string;
  sans: string;
  /** Categorical palette, `--cat-1` .. `--cat-5`. */
  cat: string[];
};

const SANS = '"Geist", ui-sans-serif, system-ui, sans-serif';

/** Token values from `tokens.css`, used when a CSS variable cannot be read. */
export const TOKEN_FALLBACK: Record<Theme, Tokens> = {
  light: {
    paper: "#F6F7F3",
    paper2: "#ECEEE8",
    ink: "#15181E",
    ink2: "#464C57",
    ink3: "#767C87",
    rule: "#D5D8D0",
    rule2: "#E4E6E0",
    best: "#00846A",
    sans: SANS,
    cat: [...SERIES_LIGHT],
  },
  dark: {
    paper: "#12161C",
    paper2: "#1A1F27",
    ink: "#E9ECEF",
    ink2: "#AEB5BF",
    ink3: "#7C8490",
    rule: "#2C333D",
    rule2: "#222830",
    best: "#1FA282",
    sans: SANS,
    cat: [...SERIES_DARK],
  },
};

const TOKEN_VARS: Record<Exclude<keyof Tokens, "cat">, string> = {
  paper: "--paper",
  paper2: "--paper-2",
  ink: "--ink",
  ink2: "--ink-2",
  ink3: "--ink-3",
  rule: "--rule",
  rule2: "--rule-2",
  best: "--best",
  sans: "--sans",
};

const MULTI_VIEW = ["facet", "hconcat", "vconcat", "concat", "repeat"];
const FACET_CHANNELS = ["row", "column", "facet"];

/** True when the spec is a composite view (`width: "container"` does not apply to it). */
export function isMultiView(spec: Obj): boolean {
  if (MULTI_VIEW.some((k) => k in spec)) return true;
  const enc = isPlain(spec.encoding) ? spec.encoding : {};
  return FACET_CHANNELS.some((k) => k in enc);
}

/**
 * True for a one-column facet (`encoding.row`, or `facet: {row}` with no `columns`) with no
 * width of its own: its cell width can be set so the whole chart fits the panel.
 */
export function isRowFacet(spec: Obj): boolean {
  const enc = isPlain(spec.encoding) ? spec.encoding : null;
  if (enc && "row" in enc && !("column" in enc) && !("facet" in enc)) return !("width" in spec);
  const facet = isPlain(spec.facet) ? spec.facet : null;
  if (facet && "row" in facet && !("column" in facet) && !("columns" in spec)) {
    const inner = isPlain(spec.spec) ? spec.spec : {};
    return !("width" in inner);
  }
  return false;
}

/** Cell width of the first embed of a row facet; the second embed fits the panel. */
export const PROBE_W = 200;

/** Message of every refused resource load. */
export const EXTERNAL_DISABLED = "external resources are disabled";

const refuse = (): Promise<never> => Promise.reject(new Error(EXTERNAL_DISABLED));

/**
 * A Vega loader that refuses every resource. Vega sends all data URLs (`load`), image and
 * link URLs (`sanitize`) and raw requests (`http`, `file`) through the view's loader, so
 * with this loader no spec can make the page fetch anything.
 */
export const DENY_LOADER: Loader = { load: refuse, sanitize: refuse, http: refuse, file: refuse };

/** Options for every embed: no action menu, SVG output, no resource loading. */
export const EMBED_OPTIONS: EmbedOptions = { actions: false, renderer: "svg", loader: DENY_LOADER };

function isPlain(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Read a CSS custom property from `<html>`. */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name);
}

/** Resolve tokens to concrete colours (Vega cannot use `var(...)`). */
export function readTokens(theme: Theme, getVar: (name: string) => string = cssVar): Tokens {
  const out = { ...TOKEN_FALLBACK[theme] };
  for (const key of Object.keys(TOKEN_VARS) as Exclude<keyof Tokens, "cat">[]) {
    const v = getVar(TOKEN_VARS[key]).trim();
    if (v) out[key] = v;
  }
  out.cat = out.cat.map((fallback, i) => getVar(`--cat-${i + 1}`).trim() || fallback);
  return out;
}

/** Chart text sizes, the same as the app's SVG charts (`FS`). */
const FONT = { tick: FS.tick, label: FS.label, title: FS.title } as const;

/**
 * Vega-Lite `config` matching the Hypothex figure style: app fonts and sizes, token
 * colours, the categorical palette for `category`, and the first palette slot for area
 * marks (bars, rects, areas, arcs), so a single-series bar is never plain ink.
 *
 * Only defaults live here: the spec's own `config` is merged on top, and encodings
 * (such as a legend `labelExpr` that turns booleans into short labels) are never touched.
 */
export function themeConfig(t: Tokens, _theme: Theme): Obj {
  const fill = t.cat[0] ?? t.ink2;
  return {
    background: "transparent",
    font: t.sans,
    view: { stroke: null },
    axis: {
      domainColor: t.ink3,
      tickColor: t.ink3,
      gridColor: t.rule2,
      labelColor: t.ink3,
      titleColor: t.ink2,
      labelFont: t.sans,
      titleFont: t.sans,
      labelFontSize: FONT.tick,
      titleFontSize: FONT.label,
      titleFontWeight: 400,
      titlePadding: 8,
      labelPadding: 4,
    },
    legend: {
      labelColor: t.ink2,
      titleColor: t.ink3,
      labelFont: t.sans,
      titleFont: t.sans,
      labelFontSize: FONT.label,
      titleFontSize: FONT.tick,
      titleFontWeight: 400,
      symbolSize: 60,
    },
    header: {
      labelColor: t.ink2,
      titleColor: t.ink2,
      labelFont: t.sans,
      titleFont: t.sans,
      labelFontSize: FONT.label,
      titleFontSize: FONT.label,
      labelFontWeight: 600,
    },
    title: { color: t.ink, font: t.sans, fontSize: FONT.title, fontWeight: 600 },
    mark: { color: t.ink },
    bar: { color: fill },
    rect: { color: fill },
    area: { color: fill },
    arc: { color: fill },
    text: { color: t.ink, font: t.sans, fontSize: FONT.label },
    range: {
      category: [...t.cat],
      ramp: [t.paper2, t.best],
      heatmap: [t.paper2, t.best],
    },
  };
}

/** Recursively merge plain objects; arrays and scalars from `over` replace. */
export function deepMerge(base: Obj, over: Obj): Obj {
  const out: Obj = { ...base };
  for (const [k, v] of Object.entries(over)) {
    const cur = out[k];
    out[k] = isPlain(v) && isPlain(cur) ? deepMerge(cur, v) : v;
  }
  return out;
}

/**
 * Build the spec to embed: copies of `rows` become `data.values` (`url`/`name` are dropped),
 * the theme is merged under the spec's own `config`, and single views fill the container
 * width. A row facet gets `cellWidth` as its cell width when given. `usermeta` is dropped, because vega-embed reads `usermeta.embedOptions` as embed
 * options (it could turn the action menu back on or name config and patch URLs). The input
 * spec is not modified.
 */
export function buildSpec(spec: Obj, rows: Obj[], config: Obj, cellWidth?: number): Obj {
  const data = isPlain(spec.data) ? spec.data : {};
  const keep = Object.fromEntries(
    Object.entries(data).filter(([k]) => k !== "url" && k !== "name" && k !== "values"),
  );
  const { usermeta: _usermeta, ...rest } = spec;
  const out: Obj = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    ...rest,
    data: { ...keep, values: rows.map((r) => ({ ...r })) },
    config: deepMerge(config, isPlain(spec.config) ? spec.config : {}),
  };
  if (!("width" in spec) && !isMultiView(spec)) {
    out.width = "container";
    if (!("autosize" in spec)) out.autosize = { type: "fit-x", contains: "padding" };
  }
  if (cellWidth !== undefined && isRowFacet(spec)) {
    if (isPlain(spec.facet)) out.spec = { ...(isPlain(spec.spec) ? spec.spec : {}), width: cellWidth };
    else out.width = cellWidth;
  }
  return out;
}

const S = {
  err: {
    fontSize: 13,
    color: "var(--fail)",
    border: "1px solid var(--rule)",
    borderRadius: 6,
    padding: "8px 10px",
    margin: "0 0 8px",
  },
} satisfies Record<string, CSSProperties>;

/** Vega-Lite panel. Reads `meta.spec`. */
export function VegaLitePanel({ result }: { result: PanelResult }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  const [error, setError] = useState<string | null>(null);
  const meta = (result.meta ?? {}) as Obj;
  const spec = isPlain(meta.spec) ? meta.spec : null;
  const rows = result.rows as Obj[];

  useEffect(() => {
    const el = ref.current;
    if (!el || !spec) return;
    let cancelled = false;
    let view: Result | null = null;
    setError(null);
    const config = themeConfig(readTokens(theme), theme);
    const fit = isRowFacet(spec);
    const draw = (cellWidth?: number): Promise<void> =>
      embed(el, buildSpec(spec, rows, config, cellWidth) as VisualizationSpec, EMBED_OPTIONS).then((r) => {
        if (cancelled) {
          r.finalize();
          return;
        }
        view = r;
        if (cellWidth !== PROBE_W) return;
        // A row facet: the chart is the cell plus labels and padding; fit it to the panel.
        const drawn = Number(el.querySelector("svg")?.getAttribute("width"));
        const target = Math.floor(el.clientWidth - (drawn - PROBE_W));
        if (!(drawn > 0) || !(el.clientWidth > 0) || target < 40 || Math.abs(target - PROBE_W) < 2) return;
        r.finalize();
        view = null;
        return draw(target);
      });
    draw(fit ? PROBE_W : undefined).catch((e: unknown) => {
      if (!cancelled) setError(e instanceof Error ? e.message : String(e));
    });
    return () => {
      cancelled = true;
      view?.finalize();
    };
  }, [spec, rows, theme]);

  if (!spec)
    return (
      <p role="alert" style={S.err}>
        No Vega-Lite spec
      </p>
    );
  return (
    <div>
      {error && (
        <p role="alert" style={S.err}>
          Vega-Lite: {error}
        </p>
      )}
      <div ref={ref} data-testid="vega" style={{ width: "100%", overflowX: "auto" }} />
    </div>
  );
}

export default VegaLitePanel;
