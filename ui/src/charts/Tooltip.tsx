/**
 * The one chart tooltip (spec section 6, mockup `showTip`): a header, then one row per
 * series with its line key, the value first, then the name. Text only (React text nodes),
 * never HTML. Charts call `showTip`/`hideTip`; `TooltipHost` (mounted once by the shell)
 * draws it next to the pointer and keeps it inside the window.
 *
 * `useTooltip` is the v4 per-chart hook still used by panels/Curves, panels/Leaderboard and
 * pages/components/SweepForest; it keeps its signature and takes the v5 look.
 */
import {
  type FocusEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import "./charts.css";

/** Pixel offset from the pointer. */
export const TIP_OFFSET = 14;

/** One tooltip row: line key colour (none = no key), value, name. */
export interface TipRow {
  color?: string;
  value: string;
  name: string;
}

export interface TipState {
  x: number;
  y: number;
  head: string;
  rows: readonly TipRow[];
}

let current: TipState | null = null;
const subscribers = new Set<() => void>();
const notify = (): void => {
  for (const fn of subscribers) fn();
};
const subscribe = (fn: () => void): (() => void) => {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
};

/** Show the tooltip at viewport position (`x`, `y`). */
export function showTip(x: number, y: number, head: string, rows: readonly TipRow[]): void {
  current = { x, y, head, rows };
  notify();
}

/** Hide the tooltip. */
export function hideTip(): void {
  if (current === null) return;
  current = null;
  notify();
}

/** The tooltip state, or null when hidden. */
export function useTipState(): TipState | null {
  return useSyncExternalStore(subscribe, () => current, () => null);
}

/** Draws the tooltip; mount once (the shell does). */
export function TooltipHost(): ReactElement | null {
  const tip = useTipState();
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !tip) return;
    const left = Math.min(window.innerWidth - el.offsetWidth - 8, tip.x + TIP_OFFSET);
    const top = Math.min(window.innerHeight - el.offsetHeight - 8, tip.y + TIP_OFFSET);
    el.style.left = `${Math.max(8, left)}px`;
    el.style.top = `${Math.max(8, top)}px`;
  }, [tip]);
  if (!tip) return null;
  return (
    <div ref={ref} className="tip" role="tooltip">
      <div className="h">{tip.head}</div>
      {tip.rows.map((row, i) => (
        <div className="r" key={`${i}-${row.name}`}>
          <i className="k" style={{ background: row.color ?? "transparent" }} />
          <b>{row.value}</b>
          <span>{row.name}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- legacy per-chart hook
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
  state: { text: string; x: number; y: number } | null;
  /** The tooltip element; render it once inside the chart. */
  node: ReactNode;
}

/**
 * Tooltip state for one v4 chart. Text may contain newlines, which render as line breaks.
 *
 * Returns
 * -------
 * Tooltip
 *     `bind(text)` handlers for marks and the `node` to render.
 */
export function useTooltip(): Tooltip {
  const [state, setState] = useState<{ text: string; x: number; y: number } | null>(null);
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
        <div role="tooltip" className="hx-tip" style={{ left: state.x + TIP_OFFSET, top: state.y + TIP_OFFSET }}>
          {state.text}
        </div>
      ) : null,
    [state],
  );
  return { bind, show, hide, state, node };
}
