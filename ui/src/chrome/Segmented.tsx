/** A segmented control: one pressed option out of a few (`By config | Each run`). */
import { type ReactElement } from "react";
import { cx } from "../lib/cx";
import "./chrome.css";

export interface SegmentedProps<T extends string> {
  options: readonly (readonly [value: T, label: string])[];
  value: T;
  onChange: (value: T) => void;
  /** Accessible name of the group, e.g. "Group". */
  label: string;
  size?: "sm";
}

export function Segmented<T extends string>({ options, value, onChange, label, size }: SegmentedProps<T>): ReactElement {
  return (
    <span className={cx("seg", size)} role="group" aria-label={label}>
      {options.map(([key, text]) => (
        <button key={key} type="button" className={key === value ? "on" : undefined} aria-pressed={key === value} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </span>
  );
}
