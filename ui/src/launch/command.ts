/**
 * Command templates for the Launch dialog. The user types one line; it is split into argv
 * the way `sh` would (quotes, backslashes), because runs execute argv directly, not through
 * a shell. `{seed}` stays in the template; hx fills it from each run's seed.
 */
import { shellJoin } from "../pages/components/format";

export const SEED_SLOT = "{seed}";

/** Substitute template vars without re-tokenizing argv or consuming the seed slot. */
export function fillVars(argv: readonly string[], vars: Readonly<Record<string, string>>): string[] {
  return argv.map((arg) => arg.replace(/\{([^{}]+)\}/g, (slot, key: string) =>
    key !== "seed" && Object.hasOwn(vars, key) ? vars[key]! : slot));
}

/** Tooltip on the command field and on each `{seed}` mark. */
export const SEED_HINT = "{seed} is filled with each seed. In a shell, quote it: '{seed}'";

/** Words a shell would treat as syntax; as argv they reach the program as plain text. */
const OPERATORS = new Set(["|", "||", "&", "&&", ";", ">", ">>", "<", "2>", "2>&1"]);

export interface SplitResult {
  argv: string[];
  /** `null` when the text splits cleanly. */
  error: string | null;
  /** Unquoted words that are shell operators, in order. */
  operators: string[];
}

/** Split a command line into argv like POSIX `sh` (no expansion of `$`, globs or `~`). */
export function splitCommand(text: string): SplitResult {
  const argv: string[] = [];
  const operators: string[] = [];
  let word = "";
  let inWord = false;
  let quoted = false;
  const endWord = (): void => {
    if (!inWord) return;
    if (!quoted && OPERATORS.has(word)) operators.push(word);
    argv.push(word);
    word = "";
    inWord = false;
    quoted = false;
  };
  let i = 0;
  while (i < text.length) {
    const c = text.charAt(i);
    if (c === "'") {
      const close = text.indexOf("'", i + 1);
      if (close < 0) return { argv: [], error: "unclosed ' quote", operators: [] };
      word += text.slice(i + 1, close);
      inWord = true;
      quoted = true;
      i = close + 1;
    } else if (c === '"') {
      let j = i + 1;
      for (;;) {
        if (j >= text.length) return { argv: [], error: 'unclosed " quote', operators: [] };
        const d = text.charAt(j);
        if (d === '"') break;
        if (d === "\\" && j + 1 < text.length && '"\\$`'.includes(text.charAt(j + 1))) {
          word += text.charAt(j + 1);
          j += 2;
        } else {
          word += d;
          j += 1;
        }
      }
      inWord = true;
      quoted = true;
      i = j + 1;
    } else if (c === "\\") {
      if (i + 1 >= text.length) return { argv: [], error: "trailing \\", operators: [] };
      const next = text.charAt(i + 1);
      if (next !== "\n") {
        word += next;
        inWord = true;
        quoted = true;
      }
      i += 2;
    } else if (/\s/.test(c)) {
      endWord();
      i += 1;
    } else {
      word += c;
      inWord = true;
      i += 1;
    }
  }
  endWord();
  return { argv, error: null, operators };
}

export interface Segment {
  text: string;
  /** True for a `{seed}` slot. */
  seed: boolean;
}

/** Render original template slots once and quote argv, highlighting only seed substitutions. */
export function previewSegments(argv: readonly string[], vars: Readonly<Record<string, string>>, seed: number): Segment[] {
  const out: Segment[] = [];
  argv.forEach((arg, index) => {
    if (index > 0) out.push({ text: " ", seed: false });
    const parts: Segment[] = [];
    let end = 0;
    for (const match of arg.matchAll(/\{([A-Za-z_][A-Za-z0-9_.]*)\}/g)) {
      if (match.index > end) parts.push({ text: arg.slice(end, match.index), seed: false });
      const key = match[1]!;
      parts.push({ text: key === "seed" ? String(seed) : Object.hasOwn(vars, key) ? vars[key]! : match[0], seed: key === "seed" });
      end = match.index + match[0].length;
    }
    if (end < arg.length) parts.push({ text: arg.slice(end), seed: false });
    const value = parts.map((part) => part.text).join("");
    const quoted = shellJoin([value]) !== value;
    if (quoted) out.push({ text: "'", seed: false });
    out.push(...parts.map((part) => ({ ...part, text: quoted ? part.text.replace(/'/g, `'"'"'`) : part.text })));
    if (quoted) out.push({ text: "'", seed: false });
  });
  return out;
}

/** Cut text into plain runs and `{seed}` slots, for highlighting. */
export function templateSegments(text: string): Segment[] {
  const out: Segment[] = [];
  text.split(SEED_SLOT).forEach((part, i) => {
    if (i > 0) out.push({ text: SEED_SLOT, seed: true });
    if (part) out.push({ text: part, seed: false });
  });
  return out;
}

/** True when any argument contains `{seed}`. */
export function hasSeedSlot(argv: readonly string[]): boolean {
  return argv.some((a) => a.includes(SEED_SLOT));
}

/** The argv with every `{seed}` replaced by `seed`. */
export function fillSeed(argv: readonly string[], seed: number): string[] {
  return argv.map((a) => a.replaceAll(SEED_SLOT, String(seed)));
}
