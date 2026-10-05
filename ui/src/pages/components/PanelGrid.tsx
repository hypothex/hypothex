/** Lay out panel results on the 12-column grid, lettered, via the panel registry. */
import { type ComponentType, createContext, useContext } from "react";
import { PANELS, PanelBoundary, PanelError } from "../../panels";
import { Figure, panelLetter } from "./Figure";
import { useInAppLinks } from "./links";
import type { RunStatus } from "../../api/models";
import type { PanelResult, PanelSpec } from "./types";

interface PanelContextProps { selectedItemId?: string; currentGroupId?: string; runStatus?: RunStatus; }
export type PanelComponent = ComponentType<{ result: PanelResult } & PanelContextProps>;
export type PanelRegistry = Partial<Record<string, PanelComponent>>;

// The registry's props allow a missing `meta`; API results always carry one, so widen
// the registry's type once here.
export const PanelRegistryContext = createContext<PanelRegistry>(PANELS as unknown as PanelRegistry);

/**
 * Render one panel result with its registered component.
 *
 * A panel whose query failed on the server (`meta.error`, with `rows: []`) shows that
 * reason instead of the panel's empty state. Unknown types and panels that throw show
 * the registry's error box, so one bad panel never blanks the page.
 */
export function PanelBody({ result, ...context }: { result: PanelResult } & PanelContextProps) {
  const registry = useContext(PanelRegistryContext);
  const onLinks = useInAppLinks();
  const failed = result.meta.error;
  if (typeof failed === "string") return <PanelError message={failed} />;
  const Component = registry[result.type];
  if (!Component) return <PanelError message={`Unknown panel type: ${result.type}`} />;
  // Panels render plain <a href> run links; route plain clicks on them in-app.
  return (
    <div className="panel-links" style={{ display: "contents" }} onClick={onLinks}>
      <PanelBoundary>
        <Component result={result} {...context} />
      </PanelBoundary>
    </div>
  );
}

/** A grid span in 1..12; missing means full width. */
export function clampSpan(span?: number): number {
  if (span === undefined || !Number.isFinite(span)) return 12;
  return Math.min(12, Math.max(1, Math.round(span)));
}

function warnings(result: PanelResult): string[] {
  const raw = result.meta.warnings;
  return Array.isArray(raw) ? raw.filter((w): w is string => typeof w === "string") : [];
}

export interface PanelGridProps extends PanelContextProps {
  results: PanelResult[];
  specs?: PanelSpec[];
  startIndex?: number;
}

export function PanelGrid({ results, specs, startIndex = 0, ...context }: PanelGridProps) {
  return (
    <div className="panel-grid">
      {results.map((result, i) => {
        const spec = specs?.[i];
        const row = spec?.layout?.row ?? undefined;
        const warn = warnings(result);
        return (
          <Figure
            key={`${i}-${result.type}`}
            letter={panelLetter(startIndex + i)}
            title={result.title || spec?.title || result.type}
            aside={warn.length ? <span title={warn.join("\n")}>⚠ {warn.length}</span> : undefined}
            style={{
              gridColumn: `span ${clampSpan(spec?.layout?.span)}`,
              gridRow: row ? String(row) : undefined,
            }}
          >
            <PanelBody result={result} {...context} />
          </Figure>
        );
      })}
    </div>
  );
}
