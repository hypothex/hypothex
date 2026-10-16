/** A pill button: a toggle (`on` given, `aria-pressed`) or a menu opener (`chevron`). */
import { type ReactElement, type ReactNode } from "react";
import { cx } from "../lib/cx";
import { Icon } from "./Icon";
import "./chrome.css";

export interface ChipProps {
  children: ReactNode;
  /** Toggle state; leave undefined for a chip that is not a toggle. */
  on?: boolean;
  onClick?: () => void;
  chevron?: boolean;
  title?: string;
  size?: "sm";
  className?: string;
}

export function Chip({ children, on, onClick, chevron = false, title, size, className }: ChipProps): ReactElement {
  return (
    <button
      type="button"
      className={cx("chip", on && "on", size, className)}
      aria-pressed={on === undefined ? undefined : on}
      onClick={onClick}
      title={title}
    >
      {children}
      {chevron ? (
        <span className="chev">
          <Icon name="chevron" size={9} />
        </span>
      ) : null}
    </button>
  );
}
