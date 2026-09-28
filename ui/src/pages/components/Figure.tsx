/** Journal-style lettered panel (spec 8.1): letter, a few-word title, optional aside. */
import type { CSSProperties, ReactNode } from "react";

/** 0 → "a", 25 → "z", 26 → "aa", 27 → "ab" (spreadsheet-style). */
export function panelLetter(index: number): string {
  let n = index;
  let out = "";
  do {
    out = String.fromCharCode(97 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}

export interface FigureProps {
  letter: string;
  title: string;
  aside?: ReactNode;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
}

export function Figure({ letter, title, aside, children, className, style }: FigureProps) {
  return (
    <section
      className={className ? `fig ${className}` : "fig"}
      style={style}
      aria-label={`${letter} ${title}`}
    >
      <header className="fig-h">
        <span className="pl">{letter}</span>
        <h2 className="t">{title}</h2>
        {aside !== undefined && aside !== null ? <span className="aside">{aside}</span> : null}
      </header>
      {children}
    </section>
  );
}
