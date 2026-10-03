/**
 * CSS for the run page's remote parts: status glyphs for queued and stale, the state bar,
 * Placement rows, the GPU cells and the queue table. Every selector starts with `.page`;
 * colours come from the theme tokens, so light and dark both work.
 */
import { createElement } from "react";

export const REMOTE_CSS = `
.page .st.queued i { background: transparent; box-shadow: inset 0 0 0 1.4px var(--ink-2); }
.page .st.stale i { background: linear-gradient(90deg, transparent 50%, var(--ink) 50%); box-shadow: inset 0 0 0 1.4px var(--ink); }
.page .state-bar { display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: baseline; margin-top: 28px; padding: 14px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 14px; color: var(--ink-2); }
.page .state-bar b { color: var(--ink); font-weight: 600; }
.page .state-bar.lost b { color: var(--fail); }
.page .state-bar .r { margin-left: auto; font-size: 12.5px; color: var(--ink-3); }
.page .place { font-size: 14px; }
.page .place-row { display: grid; grid-template-columns: 116px minmax(0, 1fr) auto; gap: 0 16px; align-items: baseline; padding: 12px 0; border-top: 1px solid var(--rule-2); }
.page .place-row:first-child { border-top: 0; padding-top: 0; }
.page .place-row .k { color: var(--ink); font-weight: 550; }
.page .place-row .v.mono { font-family: var(--mono); font-size: 13px; }
.page .place-row small { margin-left: 6px; font-size: 12.5px; color: var(--ink-3); }
.page .gpu-cells { list-style: none; display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 4px; margin: 0 0 24px; padding: 0; }
.page .gpu-cells .c { border: 1px solid var(--rule); border-left-width: 3px; border-radius: 3px; padding: 4px 6px; font-size: 12.5px; font-weight: 550; color: var(--ink); }
.page .gpu-cells .c small { display: block; font-weight: 400; color: var(--ink-3); }
.page .gpu-cells .c.run { border-left-color: var(--ink-2); background: var(--paper-2); }
.page .gpu-cells .c.ext { color: var(--ink-3); background: repeating-linear-gradient(135deg, transparent 0 4px, var(--rule-2) 4px 5px); }
.page .gpu-cells .c.free { border-style: dashed; border-left-width: 1px; color: var(--ink-3); font-weight: 400; }
.page .queue-t tr.me td { background: var(--paper-2); }
.page .queue-t tr.me td:first-child { box-shadow: inset 2px 0 0 var(--ink); padding-left: 8px; }
`;

/** Inject the remote-run CSS (one `<style>` per mounted run page). */
export function RemoteStyles() {
  return createElement("style", { "data-hx": "remote" }, REMOTE_CSS);
}
