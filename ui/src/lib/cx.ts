/** Join the truthy class names: `cx("chip", on && "on")`. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
