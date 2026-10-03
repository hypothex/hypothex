/** Sweep page CSS (mockup `docs/mockups/phase2/index.html`, block "phase 2: sweep"). Every selector starts with `.page`. */
import { type ReactElement, createElement } from "react";

export const SWEEP_CSS = `
.page .sweep-stats { margin-top: 36px; }
.page .prog { display: flex; gap: 2px; margin-top: 18px; }
.page .prog i { flex: 1; min-width: 1px; height: 10px; border-radius: 1.5px; display: block; }
.page .prog i.f { background: var(--ink-2); }
.page .prog i.r { background: var(--ink-2); opacity: .45; }
.page .prog i.q { box-shadow: inset 0 0 0 1px var(--ink-3); }
.page .prog i.x { background: var(--fail); }
.page .prog i.k { background: var(--ink-3); opacity: .3; }
.page .prog i.n { box-shadow: inset 0 0 0 1px var(--rule-2); }
.page .sw-grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 72px; margin-top: 64px; align-items: start; }
.page .sw-grid .fig { margin-top: 0; min-width: 0; }
.page .sw-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.page .add-seeds { display: flex; gap: 10px; align-items: center; font-size: 13.5px; color: var(--ink-2); }
.page .add-seeds label { display: inline-flex; gap: 8px; align-items: center; }
.page .add-seeds input { width: 64px; height: 30px; padding: 0 8px; border: 1px solid var(--rule); border-radius: 6px; background: transparent; color: var(--ink); font: inherit; font-variant-numeric: tabular-nums; }
.page .heat { border-collapse: separate; border-spacing: 4px; margin: -4px; font-variant-numeric: tabular-nums; }
.page .heat th { font: 500 12.5px/1.3 var(--sans); color: var(--ink-3); text-align: center; padding: 0 0 6px; }
.page .heat th.rh { text-align: right; padding: 0 12px 0 0; white-space: nowrap; width: 72px; }
.page .heat th.cor { text-align: right; padding: 0 12px 6px 0; white-space: nowrap; }
.page .heat td.c { background: color-mix(in srgb, var(--ink) var(--heat, 0%), transparent); box-shadow: inset 0 0 0 1px var(--rule-2); width: 168px; height: 112px; vertical-align: top; padding: 12px 14px 10px; border-radius: 5px; position: relative; }
.page .heat td.c.empty { background: transparent; box-shadow: inset 0 0 0 1px var(--rule); }
.page .heat td.c.best { box-shadow: inset 0 0 0 2px var(--best), inset 0 0 0 4px var(--paper); }
.page .heat td.c .v { font: 400 26px/1 var(--sans); letter-spacing: -.015em; display: block; cursor: help; }
.page .heat td.c .v small { font-size: 12.5px; color: var(--ink-3); letter-spacing: 0; margin-left: 6px; }
.page .heat td.c .bm { position: absolute; top: 12px; right: 12px; font-size: 12.5px; font-weight: 600; color: var(--best); }
.page .heat td.m { font-size: 13.5px; color: var(--ink-2); text-align: center; vertical-align: middle; cursor: help; }
.page .heat td.m.rm { text-align: left; padding-left: 10px; }
.page .heat .mh { font-size: 12px; color: var(--ink-3); }
.page .rl { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 14px; font-size: 12.5px; }
.page .rl a { display: inline-flex; align-items: center; gap: 4px; text-decoration-color: color-mix(in srgb, currentColor 35%, transparent); }
.page .rl .more { color: var(--ink-3); cursor: help; }
.page .ramp { display: inline-flex; gap: 2px; vertical-align: middle; }
.page .ramp i { width: 18px; height: 10px; display: block; border-radius: 1px; background: color-mix(in srgb, var(--ink) var(--heat, 0%), transparent); }
.page .best-k b { color: var(--best); font-weight: 600; }
.page .rg { display: inline-block; vertical-align: middle; overflow: visible; flex: none; }
.page .rg .fin { fill: var(--ink-2); }
.page .rg .ring { fill: none; stroke: var(--ink-3); stroke-width: 1; }
.page .rg .dot { fill: var(--ink); }
.page .rg .hollow { fill: none; stroke: var(--ink-2); stroke-width: 1.4; }
.page .rg .stale-ring { fill: none; stroke: var(--ink); stroke-width: 1.4; }
.page .rg .half { fill: var(--ink); }
.page .rg .x { fill: none; stroke: var(--fail); stroke-width: 1.8; stroke-linecap: round; }
.page .rg .x-ring { fill: none; stroke: var(--fail); stroke-width: 1.2; }
.page .rg .x.killed, .page .rg .x-ring.killed { stroke: var(--ink-3); }
.page .rg .x.killed { stroke-width: 1.5; }
.page .sw-table, .page .sw-runs { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }
.page .sw-runs { max-width: 860px; }
.page .sw-table th, .page .sw-runs th { text-align: left; font-weight: 500; color: var(--ink-3); font-size: 12.5px; padding: 0 14px 8px 0; border-bottom: 1px solid var(--rule); white-space: nowrap; }
.page .sw-table td, .page .sw-runs td { padding: 8px 14px 8px 0; border-bottom: 1px solid var(--rule-2); vertical-align: middle; white-space: nowrap; }
.page .sw-table th:first-child, .page .sw-table td:first-child, .page .sw-runs th:first-child, .page .sw-runs td:first-child { padding-left: 8px; }
.page .sw-table .r, .page .sw-runs .r { text-align: right; }
.page .sw-table th button { all: unset; cursor: pointer; }
.page .sw-table th button:focus-visible { outline: 2px solid var(--agent); outline-offset: 2px; border-radius: 3px; }
.page .sw-table th[aria-sort] button { color: var(--ink); }
.page .sw-table tr.best td { background: color-mix(in srgb, var(--best-wash) 60%, transparent); }
.page .sw-table .bm { color: var(--best); }
.page .sw-table .rl { margin-top: 0; }
.page .sw-runs td a { display: inline-flex; align-items: center; gap: 6px; }
.page .more-runs { margin-top: 12px; font-size: 13.5px; }
.page .forest { width: 100%; }
@media (max-width: 1100px) { .page .sw-grid { grid-template-columns: 1fr; gap: 48px; } }
`;

/** Inject the sweep CSS (one `<style>` per mounted Sweep page). */
export function SweepStyles(): ReactElement {
  return createElement("style", { "data-hx": "sweep" }, SWEEP_CSS);
}
