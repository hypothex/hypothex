/** The one filter field: search icon + input (runs sidebar, panel search, runs table). */
import { type ReactElement, type Ref } from "react";
import { cx } from "../lib/cx";
import { Icon } from "./Icon";
import "./chrome.css";

export interface FilterFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  /** Accessible name; defaults to the placeholder. */
  label?: string;
  size?: "sm";
  className?: string;
  inputRef?: Ref<HTMLInputElement>;
}

export function FilterField({ value, onChange, placeholder, label, size, className, inputRef }: FilterFieldProps): ReactElement {
  return (
    <div className={cx("field", size, className)} role="search">
      <Icon name="search" size={13} />
      <input
        ref={inputRef}
        type="search"
        value={value}
        placeholder={placeholder}
        aria-label={label ?? placeholder}
        spellCheck={false}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value !== "") {
            e.preventDefault();
            onChange("");
          }
        }}
      />
    </div>
  );
}
