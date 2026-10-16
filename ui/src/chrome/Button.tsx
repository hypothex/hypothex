/** The v5 button (`.btn` in styles/base.css): default, primary or ghost; md or sm; optional icon. */
import { type ButtonHTMLAttributes, type ReactElement } from "react";
import { cx } from "../lib/cx";
import { Icon, type IconName } from "./Icon";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "primary" | "ghost";
  size?: "sm" | "md";
  icon?: IconName;
  /** Square icon button; give it an `aria-label`. */
  iconOnly?: boolean;
}

export function Button({ variant = "default", size = "md", icon, iconOnly = false, className, type = "button", children, ...rest }: ButtonProps): ReactElement {
  return (
    <button
      {...rest}
      type={type}
      className={cx("btn", variant !== "default" && variant, size === "sm" && "sm", iconOnly && "icon", className)}
    >
      {icon ? <Icon name={icon} /> : null}
      {children}
    </button>
  );
}
