/**
 * The custom-view toolbar's overrides (the v4 Metric select and Seeds checkbox): a primary
 * metric for leaderboard, stat_strip and curves panels, and seed dots on leaderboard panels.
 * Other panels keep their authored axes.
 */
import type { Leaderboard, PanelSpec, ViewSpec } from "../api/models";

export interface ViewOverrides {
  primary?: string;
  seeds?: boolean;
}

/** The primary, then every recorded `metric/key` whose metric has a version. */
export function metricOptions(board: Leaderboard): string[] {
  return [...new Set([board.primary, ...board.rows.flatMap((row) => Object.keys(row.scores))])].filter(
    (ref) => /^[^/@]+\/[^/@]+$/.test(ref) && (ref.split("/")[0] ?? "") in board.metric_versions,
  );
}

export function leaderboardPanels(view: ViewSpec): PanelSpec[] {
  return view.panels?.filter((p) => p.type === "leaderboard") ?? [];
}

/** Seed dots as authored: on unless a leaderboard panel's `noise` leaves `seed` out. */
export function authoredSeeds(view: ViewSpec): boolean {
  return leaderboardPanels(view).every((p) => (p.noise ?? ["seed", "test_set"]).includes("seed"));
}

const PRIMARY_PANELS: ReadonlySet<string> = new Set(["leaderboard", "stat_strip", "curves"]);

export function applyOverrides(view: ViewSpec, { primary, seeds }: ViewOverrides): ViewSpec {
  return {
    ...view,
    panels: view.panels?.map((panel) => {
      const withPrimary = primary !== undefined && PRIMARY_PANELS.has(panel.type);
      const noise: ("seed" | "test_set")[] | undefined =
        panel.type === "leaderboard" && seeds !== undefined
          ? [...(panel.noise ?? ["seed", "test_set"]).filter((v) => v !== "seed"), ...(seeds ? (["seed"] as const) : [])]
          : undefined;
      return {
        ...panel,
        ...(withPrimary ? { data: { ...panel.data, primary } } : {}),
        ...(noise ? { noise } : {}),
      };
    }),
  };
}
