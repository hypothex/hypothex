/**
 * The runs sidebar filter language (spec section 4.2): whitespace-separated tokens, all of
 * which must hold.
 *
 * - `tag:x` a tag, `status:x` the status, `by:x` the launcher (`agent`, `tuner` or
 *   `agent:tuner` all match `agent:tuner`), `name:x` the display name (`TaskRun.name`);
 * - `key:value` or `key=value` a param (numbers compare by value, so `lr=3e-4` matches
 *   `0.0003`); `key!=value` negates any of these;
 * - `*` matches any run of characters; matching is case-insensitive;
 * - a bare word matches the display name or the derived name, or a run id prefix.
 */
import type { TaskRun } from "../api/models";

export type RunPredicate = (run: TaskRun) => boolean;

export type GlobMatcher = (value: string) => boolean;

/**
 * Prepare a `*` glob over the whole value, case-insensitive.
 *
 * The pattern is split on `*` once; the first and last pieces are anchored and the middle
 * pieces are found left to right with `indexOf`. No RegExp is built from the pattern, so a
 * crafted pattern (a shared `?q=` link) cannot cause catastrophic backtracking.
 *
 * Examples
 * --------
 * >>> compileGlob("res*")("ResNet50")
 * true
 */
export function compileGlob(pattern: string): GlobMatcher {
  const parts = pattern.toLowerCase().split("*");
  const head = parts[0] ?? "";
  if (parts.length === 1) return (value) => value.toLowerCase() === head;
  const tail = parts[parts.length - 1] ?? "";
  const middle = parts.slice(1, -1).filter(Boolean);
  return (raw) => {
    const value = raw.toLowerCase();
    const end = value.length - tail.length;
    if (end < head.length || !value.startsWith(head) || !value.endsWith(tail)) return false;
    let at = head.length;
    for (const piece of middle) {
      const found = value.indexOf(piece, at);
      if (found < 0 || found + piece.length > end) return false;
      at = found + piece.length;
    }
    return true;
  };
}

/**
 * `*` glob over the whole value, case-insensitive (see `compileGlob`).
 *
 * Examples
 * --------
 * >>> globMatch("res*", "ResNet50")
 * true
 */
export function globMatch(pattern: string, value: string): boolean {
  return compileGlob(pattern)(value);
}

function valueMatcher(pattern: string): (value: string | undefined) => boolean {
  const glob = compileGlob(pattern);
  const a = !pattern.includes("*") && pattern.trim() !== "" ? Number(pattern) : Number.NaN;
  return (value) => {
    if (value === undefined) return false;
    if (Number.isFinite(a) && value.trim() !== "") {
      const b = Number(value);
      if (Number.isFinite(b)) return a === b;
    }
    return glob(value);
  };
}

function launcherMatcher(pattern: string): GlobMatcher {
  const glob = compileGlob(pattern);
  return (who) => glob(who) || who.split(":").some(glob);
}

/**
 * Tokens of a filter, with spaces around `=`, `!=` and `:` removed.
 *
 * Examples
 * --------
 * >>> tokenize("lr = 3e-4 tag: final")
 * ["lr=3e-4", "tag:final"]
 */
export function tokenize(text: string): string[] {
  return text.replace(/\s*(!=|=|:)\s*/g, "$1").split(/\s+/).filter(Boolean);
}

function tokenPredicate(token: string): RunPredicate {
  const m = /^([^=:!]+)(!=|=|:)(.*)$/.exec(token);
  if (!m) {
    const word = token.toLowerCase();
    return (r) =>
      r.name.toLowerCase().includes(word) ||
      r.derived_name.toLowerCase().includes(word) ||
      r.run_id.toLowerCase().startsWith(word);
  }
  const [, key = "", op = ":", pattern = ""] = m;
  let pred: RunPredicate;
  switch (key.toLowerCase()) {
    case "tag": {
      const glob = compileGlob(pattern);
      pred = (r) => r.tags.some(glob);
      break;
    }
    case "status": {
      const glob = compileGlob(pattern);
      pred = (r) => glob(r.status);
      break;
    }
    case "by": {
      const match = launcherMatcher(pattern);
      pred = (r) => match(r.created_by);
      break;
    }
    case "name": {
      const glob = compileGlob(pattern);
      pred = (r) => glob(r.name);
      break;
    }
    default: {
      const match = valueMatcher(pattern);
      pred = (r) => match(r.params[key]);
    }
  }
  return op === "!=" ? (r) => !pred(r) : pred;
}

/**
 * Compile a filter string into a run predicate.
 *
 * Examples
 * --------
 * >>> runs.filter(parseFilter("lr=3e-4 tag:final"))
 */
export function parseFilter(text: string): RunPredicate {
  const preds = tokenize(text).map(tokenPredicate);
  return (run) => preds.every((p) => p(run));
}
