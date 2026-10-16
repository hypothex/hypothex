/**
 * A collapsible section of equal-size panels (spec 4.2 "Sections"). Closed sections do not
 * render their panels, so a task with 50+ score keys stays fast. With `storageKey` the open
 * state is remembered per task in localStorage.
 */
import { type ReactElement, type ReactNode, useState } from "react";
import { cx } from "../lib/cx";
import { Icon } from "./Icon";
import "./chrome.css";

export interface PanelSectionProps {
  title: string;
  count?: ReactNode;
  defaultOpen?: boolean;
  onAddPanel?: () => void;
  /** Usually `${project}/${task}`; the state lives at `hx-section:<storageKey>:<title>`. */
  storageKey?: string;
  /** Grid: `auto` (min 330 px), `fill` (auto-fit, min 380 px), `wide` (one column), `small` (min 300 px). */
  grid?: "auto" | "fill" | "wide" | "small";
  children?: ReactNode;
}

const keyOf = (storageKey: string, title: string): string => `hx-section:${storageKey}:${title}`;

function readOpen(key: string | null, fallback: boolean): boolean {
  if (key === null) return fallback;
  try {
    const v = localStorage.getItem(key);
    return v === "1" ? true : v === "0" ? false : fallback;
  } catch {
    return fallback;
  }
}

export function PanelSection({
  title,
  count,
  defaultOpen = true,
  onAddPanel,
  storageKey,
  grid = "auto",
  children,
}: PanelSectionProps): ReactElement {
  const key = storageKey ? keyOf(storageKey, title) : null;
  const [state, setState] = useState(() => ({ key, open: readOpen(key, defaultOpen) }));
  // The router keeps the page mounted across tasks: a new key re-reads that task's state.
  if (state.key !== key) setState({ key, open: readOpen(key, defaultOpen) });
  const { open } = state;
  const toggle = (): void => {
    const next = !open;
    setState({ key, open: next });
    if (key === null) return;
    try {
      localStorage.setItem(key, next ? "1" : "0");
    } catch {
      // storage disabled: the section still toggles for this page
    }
  };
  return (
    <section className={cx("sec", !open && "closed")} aria-label={title}>
      <div className="sec-h">
        <button type="button" className="sec-t" aria-expanded={open} onClick={toggle}>
          <span className="caret">
            <Icon name="chevron" size={10} />
          </span>
          <span>{title}</span>
          {count !== undefined && count !== null ? <span className="n">{count}</span> : null}
        </button>
        {onAddPanel ? (
          <button type="button" className="add" onClick={onAddPanel}>
            + Add panel
          </button>
        ) : null}
      </div>
      {open ? <div className={cx("pgrid", grid !== "auto" && grid)}>{children}</div> : null}
    </section>
  );
}
