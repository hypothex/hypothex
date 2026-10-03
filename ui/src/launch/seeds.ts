/** Seed lists for the Launch dialog: `"4, 5, 6"`, `"1-3 7"`. */

/** Most seeds one launch may start. */
export const MAX_SEEDS = 64;
const MAX_SEED = 2 ** 31 - 1;

export interface SeedParse {
  seeds: number[];
  /** `null` when the text is valid; else a short reason naming the first bad token. */
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

/** `n` seeds after the largest one used (`null` seeds ignored); `1..n` when none was used. */
export function nextSeeds(used: readonly (number | null)[], n = 3): number[] {
  const nums = used.filter((s): s is number => typeof s === "number");
  const start = nums.length > 0 ? Math.max(...nums) + 1 : 1;
  return Array.from({ length: n }, (_, i) => start + i);
}
