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

const escape = (s: string): string => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&");

/**
 * `*` glob over the whole value, case-insensitive.
 *
 * Examples
 * --------
 * >>> globMatch("res*", "ResNet50")
 * true
 */
export function globMatch(pattern: string, value: string): boolean {
  return new RegExp(`^${pattern.split("*").map(escape).join(".*")}$`, "is").test(value);
}

function valueMatch(pattern: string, value: string | undefined): boolean {
  if (value === undefined) return false;
  if (!pattern.includes("*") && pattern.trim() !== "" && value.trim() !== "") {
    const a = Number(pattern);
    const b = Number(value);
    if (Number.isFinite(a) && Number.isFinite(b)) return a === b;
  }
  return globMatch(pattern, value);
}

const launcherMatch = (pattern: string, who: string): boolean =>
  globMatch(pattern, who) || who.split(":").some((part) => globMatch(pattern, part));

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
    case "tag":
      pred = (r) => r.tags.some((t) => globMatch(pattern, t));
      break;
    case "status":
      pred = (r) => globMatch(pattern, r.status);
      break;
    case "by":
      pred = (r) => launcherMatch(pattern, r.created_by);
      break;
    case "name":
      pred = (r) => globMatch(pattern, r.name);
      break;
    default:
      pred = (r) => valueMatch(pattern, r.params[key]);
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
