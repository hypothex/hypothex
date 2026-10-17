/**
 * Server panel results in panel chrome: the foundation's `PanelGrid` (each result in a
 * `chrome/Panel`, span 12 = full row). For training, agent_eval, agent_iteration and
 * system_bench tasks a bare `/r/<id>` link inside a panel opens that run inline
 * (`onSelectRun`), as on the v4 page; every other link navigates. `query` (the Charts
 * tab's panel search) keeps the panels whose title matches.
 */
import type { ReactElement } from "react";
import { withBaselines } from "../pages/components/BaselineRows";
import type { BaselineRow, PanelResult, PanelSpec, TaskKind } from "../api/models";
import { NavigateContext, useNavigateHref } from "../pages/components/links";
import { PanelGrid } from "../pages/components/PanelGrid";
import { matchesSearch } from "./stepMetrics";

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

/** The title a panel is shown (and searched) by: the result's, else the spec's, else the type. */
export function panelTitle(result: PanelResult, spec: PanelSpec | undefined): string {
  return result.title || spec?.title || result.type;
}

export interface ViewPanelsProps {
  results: readonly PanelResult[];
  baselines?:BaselineRow[];
  specs?: readonly PanelSpec[];
  kind?: TaskKind;
  onSelectRun?: (runId: string) => void;
  /** Panel search: only panels whose title matches are drawn. */
  query?: string;
}

export function ViewPanels({ results, specs, kind, onSelectRun, query = "",baselines=[] }: ViewPanelsProps): ReactElement {
  const navigate = useNavigateHref();
  const select = (href: string): void => {
    const id = kind !== undefined && onSelectRun && INLINE_RUN_KINDS.has(kind) ? inlineRunId(href) : null;
    if (id !== null && onSelectRun) onSelectRun(id);
    else navigate(href);
  };
  const kept = results.map((result, i) => ({ result, spec: specs?.[i] })).filter(({ result, spec }) => matchesSearch(panelTitle(result, spec), query));
  const keptSpecs = specs && kept.every((k) => k.spec !== undefined) ? kept.map((k) => k.spec as PanelSpec) : undefined;
  return (
    <NavigateContext.Provider value={select}>
      <PanelGrid results={kept.map((k) => withBaselines(k.result,baselines))} specs={keptSpecs} />
    </NavigateContext.Provider>
  );
}
