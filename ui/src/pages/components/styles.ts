/** Page-level CSS. Every selector starts with `.page` so it cannot leak into the shell. */
import { createElement } from "react";

export const PAGES_CSS = `
.page { max-width: 1280px; margin: 0 auto; }
.page .crumb .tag { margin-left: 10px; }
.page h1.headline { margin: 0; max-width: 21em; font: 500 46px/1.06 var(--serif); letter-spacing: -.018em; text-wrap: balance; }
.page h1.headline.long { font-size: 27px; line-height: 1.25; font-weight: 450; max-width: 40em; text-wrap: pretty; }
.page .err { color: var(--fail); font-size: 14px; margin: 12px 0; }
.page .stats { margin: 36px 0 0; }
.page .stats > div:not([title]) { cursor: default; }
.page .fig { min-width: 0; }
.page .fig-h .t { margin: 0; }
.page .panel-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 56px 48px; margin-top: 64px; }
.page .panel-grid > .fig { margin-top: 0; }
.page .btn { display: inline-flex; align-items: center; text-decoration: none; }
.page .btn:disabled { background: transparent; }
.page .btn.link { text-decoration: underline; }
.page .copy { line-height: 0; }
.page .copy[data-state="failed"] { color: var(--fail); }
.page .row { display: flex; gap: 8px; align-items: center; }
.page .plain { list-style: none; margin: 0; padding: 0; }
.page .plain li { padding: 6px 0; }
.page .ov-grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 72px; margin-top: 64px; }
.page .ov-grid .fig { margin-top: 0; }
.page .side .fig + .fig { margin-top: 48px; }
.page .timeline svg { width: 100%; height: auto; overflow: visible; }
.page .timeline .ln { font: 600 13px var(--sans); fill: var(--ink); }
.page .timeline .lc { font: 400 12px var(--sans); fill: var(--ink-3); }
.page .timeline .grid { stroke: var(--rule-2); }
.page .timeline .lane, .page .timeline .axis { stroke: var(--rule); }
.page .timeline .tick, .page .timeline .cl { font: 400 12px var(--sans); fill: var(--ink-3); }
.page .timeline .cl.best { fill: var(--ink); font-weight: 600; }
.page .timeline .mark { cursor: pointer; }
.page .timeline .key { display: flex; flex-wrap: wrap; gap: 6px 22px; margin-top: 14px; font-size: 13px; color: var(--ink-2); }
.page .timeline .key span { display: inline-flex; align-items: center; gap: 7px; }
.page .timeline .key svg { display: block; overflow: visible; }
.page .ideas { list-style: none; margin: 0; padding: 0; }
.page .idea { display: grid; grid-template-columns: 56px minmax(0, 1fr) minmax(0, 420px) 84px; gap: 0 20px; align-items: center; padding: 14px 0; border-top: 1px solid var(--rule-2); }
.page .idea:first-child { border-top: 0; }
.page .idea .mks { display: flex; gap: 4px; align-items: center; }
.page .idea .nm { font-weight: 550; font-size: 15px; }
.page .idea .meta { font-size: 13px; color: var(--ink-3); margin-top: 1px; }
.page .idea .sc { text-align: right; font-size: 15px; font-variant-numeric: tabular-nums; }
.page .idea .sc small { display: block; font-size: 12.5px; color: var(--ink-3); }
.page .idea.dim .nm, .page .idea.dim .sc { color: var(--ink-3); font-weight: 400; }
.page .idea svg.iv { width: 100%; height: 30px; overflow: visible; }
.page .idea-axis svg { width: 100%; height: 24px; overflow: visible; }
.page .idea-axis text { font: 400 11.5px var(--sans); fill: var(--ink-3); }
.page .idea-axis .ax-l { font-size: 12.5px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.page .idea-group + .idea-group { margin-top: 18px; }
.page .fail-b { font: 400 15.5px/1.5 var(--serif); color: var(--ink-2); margin: 0 0 16px; }
.page .fail-b b { color: var(--ink); font-weight: 650; }
.page .fail-b .x { color: var(--fail); font-family: var(--sans); font-weight: 600; margin-right: 6px; }
.page .fail-b .row { margin-top: 8px; }
.page .view-tabs { display: flex; align-items: center; gap: 4px; margin-top: 36px; border-bottom: 1px solid var(--rule); font-size: 14px; }
.page .view-tabs > a { padding: 10px 12px; text-decoration: none; color: var(--ink-3); border-bottom: 2px solid transparent; margin-bottom: -1px; }
.page .view-tabs > a small { margin-left: 6px; font-size: 12px; color: var(--ink-3); }
.page .view-tabs > a[aria-current="page"] { color: var(--ink); border-bottom-color: var(--ink); font-weight: 500; }
.page .view-tabs .r { margin-left: auto; display: flex; gap: 8px; align-items: center; padding-bottom: 6px; }
.page .run-top { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 40px; align-items: start; }
.page .actions { display: flex; gap: 8px; padding-top: 10px; }
.page .status { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 18px; font-size: 14px; color: var(--ink-2); align-items: center; }
.page .st { display: inline-flex; align-items: center; gap: 6px; font-weight: 500; color: var(--ink); }
.page .st i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); }
.page .st.finished i { background: var(--best); }
.page .st.failed i, .page .st.killed i, .page .st.lost i { background: var(--fail); }
.page .st.running i { background: var(--agent); }
.page .run-grid { display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 72px; margin-top: 64px; }
.page .run-grid .fig { margin-top: 0; }
.page .run-grid .side .fig + .fig { margin-top: 56px; }
.page .tree { font-size: 14px; }
.page .tree .cmdrow { display: grid; grid-template-columns: 116px minmax(0, 1fr); gap: 0 16px; align-items: start; padding: 0 0 18px; }
.page .tree .root { display: grid; grid-template-columns: 116px minmax(0, 1fr) auto auto; gap: 0 16px; align-items: baseline; padding: 14px 0 10px; border-top: 1px solid var(--rule); }
.page .tree .k { color: var(--ink); font-weight: 550; }
.page .tree .what { font-size: 12.5px; color: var(--ink-3); text-align: right; }
.page .tree .kids { list-style: none; margin: 0 0 6px 132px; padding: 0; }
.page .tree .kids li { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto auto; gap: 0 10px; align-items: baseline; padding: 5px 0; }
.page .tree .br { color: var(--ink-3); font-family: var(--mono); font-size: 13px; }
.page .gitline { margin: 4px 0 8px 132px; font-size: 13px; color: var(--ink-3); }
.page .gitline b { color: var(--ink); font-weight: 650; font-family: var(--mono); }
.page .gitline .dirty { color: var(--fail); }
.page .tmpl { margin: 6px 0 0; font-size: 12.5px; color: var(--ink-3); }
.page .scores { width: 100%; border-collapse: collapse; }
.page .scores td { padding: 12px 0; border-top: 1px solid var(--rule-2); vertical-align: top; font-size: 14px; }
.page .scores tr:first-child td { border-top: 0; }
.page .scores .v { font: 400 30px/1 var(--sans); letter-spacing: -.015em; text-align: right; }
.page .scores small { display: block; color: var(--ink-3); font-size: 12.5px; margin-top: 4px; letter-spacing: 0; }
.page .notes { font: 400 15.5px/1.55 var(--serif); color: var(--ink-2); margin: 0 0 12px; }
.page .notes .by { font: 400 12.5px/1.4 var(--sans); color: var(--ink-3); margin-bottom: 6px; display: flex; gap: 10px; }
.page .notes p { margin: 0; white-space: pre-wrap; }
.page .notes p.clip { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.page .note-edit textarea { width: 100%; min-height: 90px; font: 400 14px/1.5 var(--sans); color: var(--ink); background: transparent; border: 1px solid var(--rule); border-radius: 6px; padding: 8px; margin-bottom: 8px; }
.page pre.log { max-height: 480px; overflow: auto; padding: 12px 14px; background: var(--paper-2); border-radius: 6px; font: 400 12.5px/1.5 var(--mono); white-space: pre-wrap; word-break: break-word; margin: 0 0 8px; }
.page .trace-pick { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 0 0 14px; font: 400 13px var(--mono); }
.page .trace-pick a { color: var(--ink-3); text-decoration: none; }
.page .trace-pick a.failed { color: var(--fail); }
.page .trace-pick a[aria-current="true"] { color: var(--ink); text-decoration: underline; }
.page .ab { display: grid; grid-template-columns: 1fr 1fr; gap: 56px; margin-top: 36px; padding: 18px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.page .ab .lbl { font-size: 12.5px; color: var(--ink-3); }
.page .ab .nm { font-weight: 600; font-size: 16px; margin-top: 2px; }
.page .ab .meta { font-size: 13px; color: var(--ink-3); margin-top: 3px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.page .ab .row { justify-content: space-between; align-items: end; gap: 20px; }
.page .ab .acc { font: 300 38px/1 var(--sans); letter-spacing: -.02em; text-align: right; }
.page .ab .acc small { display: block; font-size: 12.5px; color: var(--ink-3); font-weight: 400; letter-spacing: 0; margin-top: 4px; }
.page .two-x { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 64px; align-items: start; margin-top: 64px; }
.page .two-x .fig { margin-top: 0; }
.page .ot { border-collapse: collapse; width: 100%; }
.page .ot th { font: 500 13px/1.3 var(--sans); color: var(--ink-3); padding: 0 12px 10px; text-align: center; }
.page .ot th.rh { text-align: right; padding: 0 16px 0 0; width: 96px; vertical-align: middle; white-space: nowrap; }
.page .ot td { width: 44%; height: 124px; text-align: center; vertical-align: middle; border: 1px solid var(--rule); }
.page .ot .n { font: 300 50px/1 var(--sans); letter-spacing: -.02em; display: block; }
.page .ot .w { font-size: 13px; color: var(--ink-2); display: inline-flex; gap: 7px; align-items: center; margin-top: 6px; }
.page .ot td.fx { background: var(--best-wash); }
.page .ot td.bk { background: color-mix(in srgb, var(--fail) 10%, transparent); }
.page .ot td.same .n { color: var(--ink-2); }
.page .sw { width: 9px; height: 9px; display: inline-block; border-radius: 2px; }
.page .sw.fixed { background: var(--best); }
.page .sw.broken { background: var(--fail); }
.page .sw.both_fail { background: var(--ink-2); }
.page .sw.both_pass { background: var(--rule); }
.page .strip svg, .page .signtest svg { width: 100%; height: auto; overflow: visible; }
.page .strip rect.fixed { fill: var(--best); }
.page .strip rect.broken { fill: var(--fail); }
.page .strip rect.both_fail { fill: var(--ink-2); }
.page .strip rect.both_pass { fill: var(--rule); }
.page .strip-key { list-style: none; display: flex; gap: 22px; margin: 10px 0 0; padding: 0; font-size: 13px; color: var(--ink-2); }
.page .strip-key li { display: inline-flex; gap: 7px; align-items: center; }
.page .signtest rect { fill: var(--rule); }
.page .signtest rect[data-tail="true"] { fill: var(--ink); }
.page .signtest text { font: 400 11.5px var(--sans); fill: var(--ink-3); }
.page .signtest .obs { stroke: var(--ink-3); }
.page .signtest text.obs-l { fill: var(--ink); font-weight: 600; }
`;

/** Inject the page CSS (React dedupes nothing here; one `<style>` per mounted page). */
export function PageStyles() {
  return createElement("style", { "data-hx": "pages" }, PAGES_CSS);
}
