import { type ReactNode, useEffect, useId, useRef } from "react";
import { LaunchStyles } from "../../launch/styles";
import { ErrorBox, Loading } from "./QueryState";

/** Keep launch preparation failures inside a dismissible, retryable modal. */
export function OpeningDialog({ title, onClose, error, onRetry, children }: {
  title: string;
  onClose: () => void;
  error?: Error | null;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    const preparing = dialog.current;
    preparing?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      // A ready launch dialog may already have claimed focus during this unmount.
      const active = document.activeElement;
      if ((active === document.body || preparing?.contains(active)) && previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return <div className="hx-launch" onClick={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <LaunchStyles />
    <div ref={dialog} className="dlg" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={(event) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); }
      if (event.key === "Tab") {
        const items = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') ?? [])];
        const first = items[0];
        const last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
      <header className="dlg-h"><h2 id={titleId}>{title}</h2><button type="button" className="x" aria-label="Close" onClick={onClose}>×</button></header>
      <div className="dlg-b">{error ? <ErrorBox error={error} /> : children ?? <Loading />}</div>
      {error && onRetry ? <footer className="dlg-f"><button type="button" className="btn" onClick={onRetry}>Retry</button></footer> : null}
    </div>
  </div>;
}
