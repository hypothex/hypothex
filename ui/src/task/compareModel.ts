/**
 * Best-value rule shared by the Score keys bars (T4) and the Compare panel (T5, spec 4.2
 * "best value green"): the best of two or more distinct finite values in the task
 * direction, else null (one value, or all equal, marks nothing).
 */

export function rowBest(values: readonly (number | null)[], higherIsBetter: boolean): number | null {
  const v = values.filter((x): x is number => x !== null && Number.isFinite(x));
  if (v.length < 2 || new Set(v).size < 2) return null;
  return higherIsBetter ? Math.max(...v) : Math.min(...v);
}
