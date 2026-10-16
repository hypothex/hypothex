/** The one stroke icon set of the v5 UI (paths from docs/mockups/ui-v5). */
import { type ReactElement, type ReactNode } from "react";
import { cx } from "../lib/cx";
import "./chrome.css";

export type IconName =
  | "home" | "hosts" | "queue" | "search" | "eye" | "eye-off" | "edit" | "more" | "expand" | "chevron" | "copy"
  | "folder" | "doc" | "box" | "agent" | "human" | "check" | "x" | "warn" | "spinner" | "plus";

interface Glyph {
  box: number;
  stroke: number;
  body: ReactNode;
}

const EYE = "M1 7s2.3-4 6-4 6 4 6 4-2.3 4-6 4-6-4-6-4Z";

const GLYPHS: Record<IconName, Glyph> = {
  home: { box: 14, stroke: 1.3, body: <path d="M2 6.5 7 2l5 4.5V12H8.5V8.5h-3V12H2z" /> },
  hosts: {
    box: 14,
    stroke: 1.3,
    body: (
      <>
        <rect x="1.5" y="2.5" width="11" height="4" rx="1" />
        <rect x="1.5" y="8" width="11" height="4" rx="1" />
      </>
    ),
  },
  queue: { box: 14, stroke: 1.3, body: <path d="M2 3h10M2 7h10M2 11h6" /> },
  search: {
    box: 14,
    stroke: 1.4,
    body: (
      <>
        <circle cx="6" cy="6" r="4.3" />
        <path d="m9.2 9.2 3.3 3.3" />
      </>
    ),
  },
  eye: {
    box: 14,
    stroke: 1.2,
    body: (
      <>
        <path d={EYE} />
        <circle cx="7" cy="7" r="1.8" fill="currentColor" stroke="none" />
      </>
    ),
  },
  "eye-off": {
    box: 14,
    stroke: 1.2,
    body: (
      <>
        <path d={EYE} />
        <path d="M2 12 12 2" />
      </>
    ),
  },
  edit: { box: 14, stroke: 1.3, body: <path d="M2 12l1-3 6.5-6.5 2 2L5 11z" /> },
  more: { box: 14, stroke: 2.2, body: <path d="M3 7h.1M7 7h.1M11 7h.1" /> },
  expand: { box: 14, stroke: 1.3, body: <path d="M2 6V2h4M12 6V2H8M2 8v4h4M12 8v4H8" /> },
  chevron: { box: 10, stroke: 1.5, body: <path d="M2 3.5 5 6.5 8 3.5" /> },
  copy: {
    box: 14,
    stroke: 1.2,
    body: (
      <>
        <rect x="4.5" y="4.5" width="8" height="8" rx="1.5" />
        <path d="M9.5 4.5V3A1.5 1.5 0 0 0 8 1.5H3A1.5 1.5 0 0 0 1.5 3v5A1.5 1.5 0 0 0 3 9.5h1.5" />
      </>
    ),
  },
  folder: { box: 16, stroke: 1.2, body: <path d="M2 4.5h4l1.5 1.5H14v6.5H2z" /> },
  doc: { box: 16, stroke: 1.2, body: <path d="M4 2h5l3 3v9H4zM9 2v3h3" /> },
  box: { box: 16, stroke: 1.2, body: <path d="M2.5 5 8 2l5.5 3v6L8 14l-5.5-3zM2.5 5 8 8l5.5-3M8 8v6" /> },
  agent: {
    box: 12,
    stroke: 1.3,
    body: (
      <>
        <rect x="1.5" y="3.5" width="9" height="7" rx="2" />
        <path d="M6 1v2.5M4.3 7h.1M7.7 7h.1" strokeWidth={1.5} />
      </>
    ),
  },
  human: {
    box: 12,
    stroke: 1.3,
    body: (
      <>
        <circle cx="6" cy="4" r="2.3" />
        <path d="M1.8 11c.6-2.3 2.2-3.5 4.2-3.5s3.6 1.2 4.2 3.5" />
      </>
    ),
  },
  check: { box: 12, stroke: 1.6, body: <path d="M2.5 6.2 5 8.6l4.6-5" /> },
  x: { box: 12, stroke: 1.6, body: <path d="M3 3l6 6M9 3 3 9" /> },
  warn: {
    box: 12,
    stroke: 1.4,
    body: (
      <>
        <path d="M6 1.5 11 10.5H1z" />
        <path d="M6 5v2.5M6 9v.1" />
      </>
    ),
  },
  spinner: {
    box: 12,
    stroke: 1.6,
    body: (
      <g className="spin">
        <circle cx="6" cy="6" r="4.2" strokeDasharray="18 8" />
      </g>
    ),
  },
  plus: { box: 14, stroke: 1.4, body: <path d="M7 2.5v9M2.5 7h9" /> },
};

export const ICON_NAMES: readonly IconName[] = Object.keys(GLYPHS) as IconName[];

export interface IconProps {
  name: IconName;
  /** CSS px; defaults to the glyph's own box (10, 12, 14 or 16). */
  size?: number;
  /** Accessible name; without it the icon is decorative. */
  label?: string;
  className?: string;
}

export function Icon({ name, size, label, className }: IconProps): ReactElement {
  const g = GLYPHS[name];
  const px = size ?? g.box;
  return (
    <svg
      className={cx("ico", className)}
      width={px}
      height={px}
      viewBox={`0 0 ${g.box} ${g.box}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={g.stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : "true"}
      role={label ? "img" : undefined}
      aria-label={label}
    >
      {g.body}
    </svg>
  );
}
