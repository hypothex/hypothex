/**
 * Project avatar (spec section 7): an 18 px rounded square with the initials in one of 8
 * muted hues, hashed from the project name, on a tint of the same hue. The hues never
 * compete with run identity colours.
 */
import { type CSSProperties, type ReactElement } from "react";
import { cx } from "../lib/cx";
import "./chrome.css";

export const AVATAR_HUES = ["#4f5fc0", "#1f8a7a", "#8a4fb0", "#bf6a2a", "#5a7386", "#b8407a", "#3a8a4e", "#8a6a48"] as const;

export function avatarHue(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_HUES[h % AVATAR_HUES.length] ?? AVATAR_HUES[0];
}

export function initials(name: string): string {
  const out = name
    .split(/[-_ ]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase();
  return out || "?";
}

export function Avatar({ name, size = "md" }: { name: string; size?: "md" | "sm" }): ReactElement {
  return (
    <span className={cx("av", size === "sm" && "sm")} style={{ "--av": avatarHue(name) } as CSSProperties} aria-hidden="true">
      {initials(name)}
    </span>
  );
}
