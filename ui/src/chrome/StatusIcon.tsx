/** Run status: a glyph and a word, never colour alone (spec section 7). */
import { type ReactElement, type ReactNode } from "react";
import type { RunStatus } from "../api/models";
import { Icon } from "./Icon";
import "./chrome.css";

export type StatusKind = RunStatus | "stale";

export const STATUS_WORD: Record<StatusKind, string> = {
  finished: "finished",
  running: "running",
  queued: "queued",
  failed: "failed",
  killed: "killed",
  lost: "lost",
  stale: "stale",
};

function Glyph({ status }: { status: StatusKind }): ReactElement {
  switch (status) {
    case "finished":
      return <Icon name="check" />;
    case "running":
      return <Icon name="spinner" />;
    case "failed":
      return <Icon name="x" />;
    case "lost":
      return <Icon name="warn" />;
    default:
      return (
        <svg className="ico" width={12} height={12} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" aria-hidden="true">
          {status === "queued" ? <circle cx="6" cy="6" r="4.2" strokeDasharray="2 2" /> : null}
          {status === "killed" ? <rect x="3.2" y="3.2" width="5.6" height="5.6" rx="1" /> : null}
          {status === "stale" ? (
            <>
              <circle cx="6" cy="6" r="4.4" />
              <path d="M6 3.6V6l1.7 1.1" />
            </>
          ) : null}
        </svg>
      );
  }
}

export interface StatusIconProps {
  status: StatusKind;
  /** Text after the glyph (default: the status word), e.g. "failed · exit 137". */
  label?: ReactNode;
  /** Glyph only; the word becomes its accessible name. */
  iconOnly?: boolean;
  title?: string;
}

export function StatusIcon({ status, label, iconOnly = false, title }: StatusIconProps): ReactElement {
  return (
    <span
      className={`st ${status}`}
      title={title}
      role={iconOnly ? "img" : undefined}
      aria-label={iconOnly ? STATUS_WORD[status] : undefined}
    >
      <Glyph status={status} />
      {iconOnly ? null : (label ?? STATUS_WORD[status])}
    </span>
  );
}
