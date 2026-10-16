/**
 * Identity colour (spec principle 1): visible identities take `--c1`..`--c8` in list
 * order; the 9th and later, and identities not in the list, are the neutral `--c0`.
 */
export const IDENTITY_SLOTS = 8;
export const NEUTRAL = "var(--c0)";

/**
 * The colour of `id` among the visible identities.
 *
 * Examples
 * --------
 * >>> colorFor("b", ["a", "b"])
 * "var(--c2)"
 */
export function colorFor(id: string, visibleOrder: readonly string[]): string {
  const i = visibleOrder.indexOf(id);
  return i >= 0 && i < IDENTITY_SLOTS ? `var(--c${i + 1})` : NEUTRAL;
}
