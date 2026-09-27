/**
 * Hover tooltips for SVG marks.
 *
 * Page copy stays terse; explanations and exact numbers live in these tooltips.
 * Text may contain newlines, which render as line breaks.
 */
import { useCallback, useMemo, useState, type FocusEvent, type MouseEvent, type ReactNode } from "react";

/** Where and what the tooltip shows. */
export interface TipState {
  text: string;
  x: number;
  y: number;
}

/** Event handlers that show a tooltip for one mark. */
export interface TipHandlers {
  onMouseEnter: (e: MouseEvent<Element>) => void;
  onMouseMove: (e: MouseEvent<Element>) => void;
  onMouseLeave: () => void;
  onFocus: (e: FocusEvent<Element>) => void;
  onBlur: () => void;
}

/** What {@link useTooltip} returns. */
export interface Tooltip {
  /** Handlers to spread on a mark: `<rect {...tip.bind("mean 0.92")} />`. */
  bind: (text: string) => TipHandlers;
  /** Show `text` at viewport position (`x`, `y`). */
  show: (text: string, x: number, y: number) => void;
  /** Hide the tooltip. */
  hide: () => void;
  /** Current state, `null` when hidden. */
  state: TipState | null;
  /** The tooltip element; render it once inside the chart. */
  node: ReactNode;
}

/** Pixel offset from the pointer. */
export const TIP_OFFSET = 12;

/**
 * Tooltip state for one chart.
 *
 * Returns
 * -------
 * Tooltip
 *     `bind(text)` handlers for marks and the `node` to render.
 */
export function useTooltip(): Tooltip {
  const [state, setState] = useState<TipState | null>(null);
  const show = useCallback((text: string, x: number, y: number) => setState({ text, x, y }), []);
  const hide = useCallback(() => setState(null), []);
  const bind = useCallback(
    (text: string): TipHandlers => ({
      onMouseEnter: (e) => show(text, e.clientX, e.clientY),
      onMouseMove: (e) => show(text, e.clientX, e.clientY),
      onMouseLeave: hide,
      onFocus: (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        show(text, r.left + r.width / 2, r.top);
      },
      onBlur: hide,
    }),
    [show, hide],
  );
  const node = useMemo(
    () =>
      state ? (
        <div
          role="tooltip"
          className="hx-tip"
          style={{ left: state.x + TIP_OFFSET, top: state.y + TIP_OFFSET }}
        >
          {state.text}
        </div>
      ) : null,
    [state],
  );
  return { bind, show, hide, state, node };
}
