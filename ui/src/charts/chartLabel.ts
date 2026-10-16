/**
 * The accessible name of the charts inside a panel: `chrome/Panel` provides its label (or
 * title), and every chart svg reads it, so a screen reader hears "val/loss", not "image".
 */
import { createContext, useContext } from "react";

export const ChartLabelContext = createContext<string | null>(null);

/**
 * The enclosing panel's label, else `fallback`.
 *
 * Examples
 * --------
 * >>> const label = useChartLabel("Line chart"); // "val/loss" inside <Panel title="val/loss">
 */
export function useChartLabel(fallback: string): string {
  return useContext(ChartLabelContext) ?? fallback;
}
