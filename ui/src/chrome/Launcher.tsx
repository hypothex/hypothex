/** Who launched a run: an agent or human glyph and the name (`agent:tuner` -> tuner). */
import { type ReactElement } from "react";
import { Icon } from "./Icon";
import "./chrome.css";

export function launcherKind(who: string): "agent" | "human" {
  return who.startsWith("agent") ? "agent" : "human";
}

export function launcherName(who: string): string {
  const i = who.indexOf(":");
  if (i < 0) return who;
  return who.slice(i + 1) || who.slice(0, i);
}

export function Launcher({ who }: { who: string }): ReactElement {
  return (
    <span className="st launcher" title={who}>
      <Icon name={launcherKind(who)} />
      <span className="ln">{launcherName(who)}</span>
    </span>
  );
}
