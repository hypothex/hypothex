/**
 * Server panel results in panel chrome: the foundation's `PanelGrid` (each result in a
 * `chrome/Panel`, span 12 = full row). For training, agent_eval, agent_iteration and
 * system_bench tasks a bare `/r/<id>` link inside a panel opens that run inline
 * (`onSelectRun`), as on the v4 page; every other link navigates.
 */
import type { ReactElement } from "react";
import type { PanelResult, PanelSpec, TaskKind } from "../api/models";
import { NavigateContext, useNavigateHref } from "../pages/components/links";
import { PanelGrid } from "../pages/components/PanelGrid";

export const INLINE_RUN_KINDS: ReadonlySet<TaskKind> = new Set<TaskKind>(["training", "agent_eval", "agent_iteration", "system_bench"]);

/** The run id of a bare `/r/<id>` link (no query, no hash), else null. */
export function inlineRunId(href: string): string | null {
  const match = /^\/r\/([^/?#]+)$/.exec(href);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1] as string);
  } catch {
    return null;
  }
}

export interface ViewPanelsProps {
  results: readonly PanelResult[];
  specs?: readonly PanelSpec[];
  kind?: TaskKind;
  onSelectRun?: (runId: string) => void;
}

export function ViewPanels({ results, specs, kind, onSelectRun }: ViewPanelsProps): ReactElement {
  const navigate = useNavigateHref();
  const select = (href: string): void => {
    const id = kind !== undefined && onSelectRun && INLINE_RUN_KINDS.has(kind) ? inlineRunId(href) : null;
    if (id !== null && onSelectRun) onSelectRun(id);
    else navigate(href);
  };
  return (
    <NavigateContext.Provider value={select}>
      <PanelGrid results={[...results]} specs={specs ? [...specs] : undefined} />
    </NavigateContext.Provider>
  );
}
