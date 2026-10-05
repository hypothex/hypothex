/** Seed lists for the Launch dialog: `"4, 5, 6"`, `"1-3 7"`. */

/** Most seeds one launch may start. */
export const MAX_SEEDS = 64;
export const MAX_SEED = 2 ** 31 - 1;

export interface SeedParse {
  seeds: number[];
  /** `null` when valid; else an empty-list/count error or the first bad token. */
  error: string | null;
}

/**
 * Parse a seed list: non-negative integers and inclusive ranges `a-b`, separated by commas
 * or whitespace. Repeats are dropped; the first occurrence keeps its place.
 */
export function parseSeeds(text: string): SeedParse {
  const tokens = text.split(/[\s,]+/).filter(Boolean);
  if (tokens.length === 0) return { seeds: [], error: "none" };
  const out: number[] = [];
  const seen = new Set<number>();
  for (const token of tokens) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(token);
    if (m === null) return { seeds: [], error: `bad seed ${token}` };
    const lo = Number(m[1]);
    const hi = m[2] === undefined ? lo : Number(m[2]);
    if (hi > MAX_SEED || lo > MAX_SEED) return { seeds: [], error: `seed too large: ${token}` };
    if (hi < lo) return { seeds: [], error: `bad range ${token}` };
    if (hi - lo >= MAX_SEEDS) return { seeds: [], error: `at most ${MAX_SEEDS} seeds` };
    for (let seed = lo; seed <= hi; seed += 1) {
      if (!seen.has(seed)) {
        seen.add(seed);
        out.push(seed);
      }
    }
    if (out.length > MAX_SEEDS) return { seeds: [], error: `at most ${MAX_SEEDS} seeds` };
  }
  return { seeds: out, error: null };
}

/** Up to `n` higher valid seeds; empty at MAX_SEED, never wrapping to an earlier seed. */
export function nextSeeds(used: readonly (number | null)[], n = 3): number[] {
  let largest = 0;
  for (const seed of used) if (seed !== null && seed > largest) largest = seed;
  const start = largest + 1;
  return Array.from({ length: Math.max(0, Math.min(n, MAX_SEED - largest)) }, (_, i) => start + i);
}
