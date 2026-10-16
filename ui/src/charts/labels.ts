/** Label fitting for SVG charts (no text measuring: Geist is about 0.535 em per character). */

/** Characters of `fontPx` text that fit in `px`. */
export function charsFor(px: number, fontPx = 12): number {
  return Math.max(1, Math.floor(px / (fontPx * 0.535)));
}

/** `text` cut to `maxChars` with a trailing `…`. */
export function clip(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 1))}…`;
}
