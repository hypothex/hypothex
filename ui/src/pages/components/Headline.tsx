/**
 * Page headline text that wraps at spaces only.
 *
 * Browsers also break after a hyphen, so `1e-4` could wrap as `1e-` / `4`. Each
 * space-separated token is a `white-space: nowrap` span; the spaces between them stay
 * normal, so lines break there and nowhere else.
 */
import type { ReactElement } from "react";

/** Split `text` into tokens and the whitespace runs between them. */
export function tokens(text: string): string[] {
  return text.split(/(\s+)/).filter((t) => t !== "");
}

/** `text` with every token kept whole on one line. */
export function Unbroken({ text }: { text: string }): ReactElement {
  return (
    <>
      {tokens(text).map((t, i) =>
        /^\s+$/.test(t) ? (
          t
        ) : (
          <span key={i} className="nb">
            {t}
          </span>
        ),
      )}
    </>
  );
}
