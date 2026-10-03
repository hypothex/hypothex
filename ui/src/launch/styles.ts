/** Launch dialog CSS, from the phase 2 mockup. Every selector starts with `.hx-launch`. */
import { type ReactElement, createElement } from "react";

export const LAUNCH_CSS = `
.hx-launch { position: fixed; inset: 0; z-index: 30; display: flex; justify-content: center; align-items: flex-start; padding: 84px 16px 0; overflow: auto; background: color-mix(in srgb, var(--ink) 24%, transparent); }
[data-theme="dark"] .hx-launch { background: rgba(0, 0, 0, .55); }
.hx-launch .dlg { width: 840px; max-width: 100%; background: var(--paper); border: 1px solid var(--rule); border-radius: 10px; box-shadow: 0 24px 60px -20px rgba(10, 14, 20, .35); margin-bottom: 60px; }
.hx-launch .dlg-h { display: flex; align-items: baseline; gap: 14px; padding: 18px 24px 14px; border-bottom: 1px solid var(--rule); }
.hx-launch .dlg-h h2 { margin: 0; font: 500 24px/1.1 var(--serif); letter-spacing: -.01em; }
.hx-launch .dlg-h .x { margin-left: auto; border: 0; background: transparent; color: var(--ink-3); font-size: 20px; line-height: 1; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.hx-launch .dlg-h .x:hover { color: var(--ink); background: var(--paper-2); }
.hx-launch .dlg-b { padding: 8px 24px 4px; }
.hx-launch .fr { display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 0 16px; align-items: baseline; padding: 14px 0; border-top: 1px solid var(--rule-2); }
.hx-launch .fr:first-child { border-top: 0; }
.hx-launch .fr > label, .hx-launch .fr > .lb { font-weight: 550; font-size: 14px; color: var(--ink); }
.hx-launch .row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hx-launch .pair { display: inline-flex; align-items: center; gap: 6px; }
.hx-launch .r { margin-left: auto; }
.hx-launch .bad { color: var(--fail); }
.hx-launch .warn { color: var(--ink-2); }
.hx-launch p.bad, .hx-launch p.warn { margin: 6px 0 0; }
.hx-launch .err { color: var(--fail); font-size: 14px; margin: 4px 24px 8px; }
.hx-launch .in { height: 32px; box-sizing: border-box; border: 1px solid var(--rule); border-radius: 6px; background: transparent; padding: 0 10px; font-size: 14px; color: var(--ink); }
.hx-launch .in:focus { outline: 2px solid var(--agent); outline-offset: 0; border-color: transparent; }
.hx-launch .in[aria-invalid="true"] { border-color: var(--fail); }
.hx-launch .in.mono { font-family: var(--mono); font-size: 13px; }
.hx-launch .in.w-s { width: 160px; }
.hx-launch .in.w-m { width: 112px; font-variant-numeric: tabular-nums; }
.hx-launch .in.w-l { width: 100%; }
.hx-launch .lbl-x { font-size: 12.5px; color: var(--ink-3); font-weight: 400; }
.hx-launch .stp { display: inline-flex; align-items: center; border: 1px solid var(--rule); border-radius: 6px; height: 32px; box-sizing: border-box; }
.hx-launch .stp button { width: 30px; height: 30px; border: 0; background: transparent; color: var(--ink-2); cursor: pointer; font-size: 16px; }
.hx-launch .stp button:hover:not(:disabled) { color: var(--ink); }
.hx-launch .stp button:disabled { color: var(--rule); cursor: not-allowed; }
.hx-launch .stp output { min-width: 26px; text-align: center; font-variant-numeric: tabular-nums; font-size: 14px; }
.hx-launch .sw { position: relative; display: inline-flex; align-items: center; gap: 9px; cursor: pointer; font-size: 14px; color: var(--ink-2); }
.hx-launch .sw input { position: absolute; opacity: 0; }
.hx-launch .sw .tr { width: 30px; height: 18px; border-radius: 9px; background: var(--rule); position: relative; transition: background .12s; flex: none; }
.hx-launch .sw .tr::after { content: ""; position: absolute; left: 2px; top: 2px; width: 14px; height: 14px; border-radius: 50%; background: var(--paper); transition: transform .12s; }
.hx-launch .sw input:checked + .tr { background: var(--ink); }
.hx-launch .sw input:checked + .tr::after { transform: translateX(12px); }
.hx-launch .sw input:focus-visible + .tr { outline: 2px solid var(--agent); outline-offset: 2px; }
.hx-launch .hp { display: grid; border: 1px solid var(--rule); border-radius: 7px; overflow: hidden; }
.hx-launch .hp label { display: grid; grid-template-columns: 18px 92px 56px minmax(0, 1fr) 84px 52px; gap: 0 12px; align-items: center; padding: 8px 12px; cursor: pointer; font-size: 14px; border-top: 1px solid var(--rule-2); font-variant-numeric: tabular-nums; }
.hx-launch .hp label:first-child { border-top: 0; }
.hx-launch .hp label:hover { background: color-mix(in srgb, var(--paper-2) 55%, transparent); }
.hx-launch .hp label.on { background: var(--paper-2); box-shadow: inset 2px 0 0 var(--ink); }
.hx-launch .hp label.off { color: var(--ink-3); cursor: not-allowed; }
.hx-launch .hp input { appearance: none; -webkit-appearance: none; margin: 0; width: 14px; height: 14px; border-radius: 50%; border: 1.4px solid var(--ink-3); display: grid; place-content: center; }
.hx-launch .hp input:checked { border-color: var(--ink); }
.hx-launch .hp input:checked::after { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--ink); }
.hx-launch .hp input:disabled { border-color: var(--rule); }
.hx-launch .hp .nm { font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hx-launch .hp .tag { justify-self: start; }
.hx-launch .hp .fr-n { text-align: right; color: var(--ink-2); white-space: nowrap; }
.hx-launch .hp .fr-n b { color: var(--ink); font-weight: 600; }
.hx-launch .hp .qq { text-align: right; color: var(--ink-3); font-size: 13px; }
.hx-launch .mini { display: flex; gap: 2px; align-items: center; }
.hx-launch .mini i { width: 9px; height: 12px; border-radius: 1.5px; display: block; }
.hx-launch .mini i.busy { background: var(--ink-2); }
.hx-launch .mini i.free { box-shadow: inset 0 0 0 1px var(--ink-3); }
.hx-launch .mini i.other { box-shadow: inset 0 0 0 1px var(--rule); background: repeating-linear-gradient(135deg, var(--ink-3) 0 1px, transparent 1px 3px); }
.hx-launch .mini i.stale { background: var(--ink-3); opacity: .35; }
.hx-launch .mini i.none { box-shadow: inset 0 0 0 1px var(--rule-2); }
.hx-launch .tmpl { position: relative; border: 1px solid var(--rule); border-radius: 6px; font: 400 13px/1.6 var(--mono); }
.hx-launch .tmpl:focus-within { outline: 2px solid var(--agent); border-color: transparent; }
.hx-launch .tmpl-hl, .hx-launch .tmpl textarea { margin: 0; padding: 6px 10px; box-sizing: border-box; font: inherit; letter-spacing: normal; white-space: pre-wrap; overflow-wrap: anywhere; }
.hx-launch .tmpl-hl { color: var(--ink); min-height: 32px; }
.hx-launch .tmpl textarea { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: transparent; color: transparent; caret-color: var(--ink); resize: none; overflow: hidden; outline: none; }
.hx-launch .tmpl textarea::placeholder { color: var(--ink-3); }
.hx-launch .tok { background: var(--best-wash); color: var(--ink); border-radius: 3px; box-shadow: inset 0 0 0 1px var(--best-edge); font-weight: inherit; }
.hx-launch .where { margin-top: 6px; }
.hx-launch .sb { flex-basis: 100%; font-size: 12px; color: var(--ink-3); }
.hx-launch .prev { display: flex; align-items: center; gap: 10px; }
.hx-launch .prev .cmd { flex: 1; min-width: 0; padding: 8px 12px; }
.hx-launch .hostp { color: var(--ink-3); }
.hx-launch .xn { font-size: 12.5px; color: var(--ink-3); }
.hx-launch .dlg-f { display: flex; align-items: center; gap: 8px; padding: 14px 24px; border-top: 1px solid var(--rule); }
.hx-launch .dlg-f .sum { margin-left: auto; margin-right: 4px; }
`;

/** Inject the dialog CSS while the dialog is mounted. */
export function LaunchStyles(): ReactElement {
  return createElement("style", { "data-hx": "launch" }, LAUNCH_CSS);
}
