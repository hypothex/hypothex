/** Copy a path or command to the clipboard, with a visible result. */
import { useEffect, useState } from "react";

type CopyState = "idle" | "copied" | "failed";

const TITLES: Record<CopyState, string> = {
  idle: "Copy",
  copied: "Copied",
  failed: "Clipboard blocked",
};

function CopyIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
      <rect x="3.5" y="3.5" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" />
      <path d="M9 1.5H2.5a1 1 0 0 0-1 1V9" fill="none" stroke="currentColor" />
    </svg>
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [state, setState] = useState<CopyState>("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 1500);
    return () => clearTimeout(timer);
  }, [state]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  };
  return (
    <button
      type="button"
      className="copy"
      data-state={state}
      title={TITLES[state]}
      aria-label={`Copy ${label ?? text}`}
      onClick={copy}
    >
      {state === "copied" ? "✓" : state === "failed" ? "!" : <CopyIcon />}
    </button>
  );
}
