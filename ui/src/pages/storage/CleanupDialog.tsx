import { type ReactNode, useEffect, useRef } from "react";
import { LaunchStyles } from "../../launch/styles";
/** Destructive modal keeps focus and cannot imply cancellation after Apply starts. */
export function CleanupDialog({ pending, onClose, children }: { pending: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { const previous = document.activeElement; ref.current?.querySelector<HTMLElement>("input, button")?.focus(); return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); }; }, []);
  return <div className="hx-launch"><LaunchStyles /><div className="dlg" ref={ref} role="dialog" aria-modal="true" aria-label="Apply cleanup" onKeyDown={(e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); if (!pending) onClose(); }
    if (e.key === "Tab") { const targets = [...(ref.current?.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),[tabindex='0']") ?? [])]; const first = targets[0]; const last = targets.at(-1); if (!targets.length) e.preventDefault(); else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); } }
  }}><header className="dlg-h"><h2>Apply cleanup</h2><button className="x" aria-label="Close" disabled={pending} onClick={onClose}>×</button></header><div className="dlg-b">{children}{pending ? <p role="status">Deletion is in progress. Closing cannot cancel server cleanup.</p> : null}</div></div></div>;
}
