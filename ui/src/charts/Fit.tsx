/**
 * Measure the available width and draw a chart at that real pixel size (spec section 6):
 * charts use `viewBox = 0 0 width height` and `width = width`, so text never scales.
 */
import { type ReactElement, type ReactNode, useLayoutEffect, useRef, useState } from "react";

export interface FitProps {
  /** Draw the chart for a width in CSS px (an integer > 0). */
  children: (width: number) => ReactNode;
  /** Height kept before the first measure, so the page does not jump. */
  minHeight?: number;
}

export function Fit({ children, minHeight }: FitProps): ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = (w: number): void => {
      const px = Math.floor(w);
      if (px > 0) setWidth(px);
    };
    read(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) read(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={ref} className="fit" style={minHeight ? { minHeight } : undefined}>
      {width > 0 ? children(width) : null}
    </div>
  );
}
