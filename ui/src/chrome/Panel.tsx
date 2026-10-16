/**
 * Panel chrome (spec principle 5, section 6): a white card with a title, an optional unit
 * and aside, always-visible tools, and hover tools (Full screen, Edit, More). It replaces
 * the v4 lettered `Figure`; the section is a region named by the title and carries
 * `data-panel` so tests and pages can find the enclosing panel.
 */
import { type CSSProperties, type ReactElement, type ReactNode, type Ref, useEffect, useRef, useState } from "react";
import { ChartLabelContext } from "../charts/chartLabel";
import { cx } from "../lib/cx";
import { Icon } from "./Icon";
import "./chrome.css";

export interface PanelMenuItem {
  label: string;
  onSelect: () => void;
}

export interface PanelProps {
  title: string;
  /** Accessible name of the region when it must differ from the title (default: the title). */
  label?: string;
  /** Ref to the title heading; the heading then takes programmatic focus (`tabIndex -1`). */
  headingRef?: Ref<HTMLHeadingElement>;
  unit?: ReactNode;
  aside?: ReactNode;
  /** Controls that stay visible (e.g. a `Table | Bars` switch). */
  tools?: ReactNode;
  onEdit?: () => void;
  menu?: readonly PanelMenuItem[];
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export function Panel({ title, label, headingRef, unit, aside, tools, onEdit, menu, className, style, children }: PanelProps): ReactElement {
  const [full, setFull] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLSpanElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setFull(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [full]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: Event): void => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [menuOpen]);

  const hasAside = aside !== undefined && aside !== null && aside !== false && aside !== "";
  return (
    <section className={cx("panel", full && "full", className)} style={style} aria-label={label ?? title} data-panel="">
      <header className="panel-h">
        <h3 ref={headingRef} tabIndex={headingRef ? -1 : undefined} className="t" title={title}>
          {title}
        </h3>
        {unit ? <span className="u">{unit}</span> : null}
        <span className="sp" />
        {hasAside ? <span className="aside">{aside}</span> : null}
        {tools}
        <span className="pacts">
          <button
            type="button"
            title={full ? "Exit full screen" : "Full screen"}
            aria-label="Full screen"
            aria-pressed={full}
            onClick={() => setFull((f) => !f)}
          >
            <Icon name="expand" />
          </button>
          {onEdit ? (
            <button type="button" title="Edit panel" aria-label="Edit panel" onClick={onEdit}>
              <Icon name="edit" />
            </button>
          ) : null}
          {menu && menu.length > 0 ? (
            <span
              className="pmenu"
              ref={menuRef}
              onKeyDown={(e) => {
                // Escape closes the menu only; it does not also leave full screen.
                if (e.key === "Escape" && menuOpen) {
                  e.stopPropagation();
                  setMenuOpen(false);
                  moreRef.current?.focus();
                }
              }}
            >
              <button
                ref={moreRef}
                type="button"
                title="More"
                aria-label="More"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((o) => !o)}
              >
                <Icon name="more" />
              </button>
              {menuOpen ? (
                <ul className="menu" role="menu">
                  {menu.map((item) => (
                    <li key={item.label} role="none">
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setMenuOpen(false);
                          item.onSelect();
                        }}
                      >
                        {item.label}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </span>
          ) : null}
        </span>
      </header>
      <div className="panel-b">
        <ChartLabelContext.Provider value={label ?? title}>{children}</ChartLabelContext.Provider>
      </div>
    </section>
  );
}
