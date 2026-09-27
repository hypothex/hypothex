/**
 * Panel registry: maps a `PanelType` to the component that draws its `PanelResult`.
 *
 * Every panel component takes `{ result }`. Unknown types and panels that throw while
 * rendering show a small error box instead of breaking the page.
 */
import { Component, createElement, type ComponentType, type ReactElement, type ReactNode } from "react";
import type { PanelResult as ApiPanelResult, PanelType } from "../api/models";
import { Leaderboard } from "./Leaderboard";
import { StatStrip } from "./StatStrip";
import "./panels.css";

/** Panel types (contract 1.4), from the API models. */
export type { PanelType };

/**
 * Server-computed panel data, derived from `../api/models`'s `PanelResult` (the one
 * hand-written copy of the contract shape) with `meta` widened to optional, so API
 * results pass straight in and hand-built results in tests need no `meta`.
 */
export type PanelResult = Omit<ApiPanelResult, "meta"> & {
  meta?: Record<string, unknown>;
};

/** Props every panel component takes. */
export interface PanelProps {
  result: PanelResult;
}

/** Registered panel components. Later panel groups add their entries here. */
export const PANELS: Partial<Record<PanelType, ComponentType<PanelProps>>> = {
  stat_strip: StatStrip,
  leaderboard: Leaderboard,
};

/** Return the component for `type`, or `null` if none is registered. */
export function panelFor(type: string): ComponentType<PanelProps> | null {
  return Object.hasOwn(PANELS, type) ? (PANELS[type as PanelType] ?? null) : null;
}

/** A small error box. */
export function PanelError({ message }: { message: string }): ReactElement {
  return createElement("div", { className: "panel-error", role: "alert" }, message);
}

interface BoundaryState {
  error: Error | null;
}

/** Catch render errors in one panel so the rest of the view still draws. */
export class PanelBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override render(): ReactNode {
    return this.state.error
      ? createElement(PanelError, { message: `Panel failed: ${this.state.error.message}` })
      : this.props.children;
  }
}

/** Render `result` with its registered component, inside an error boundary. */
export function Panel({ result }: PanelProps): ReactElement {
  const C = panelFor(result.type);
  if (!C) return createElement(PanelError, { message: `Unknown panel type: ${result.type}` });
  return createElement(PanelBoundary, null, createElement(C, { result }));
}
