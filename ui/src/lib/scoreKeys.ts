/**
 * Score keys of eval tasks (spec section 4.2 "Score keys", "Compare"):
 * `<prefix>/<dataset>.<model>.<metric>`, `<prefix>/<dataset>.<metric>` or a bare metric.
 * The split rule is the backend's `core/scorekeys.split_score_key`.
 */

export type KeyParts = { prefix: string; dataset: string | null; model: string | null; metric: string };
export type KeySection = { metric: string; panels: { key: string; title: string }[] };

function prefixAndTail(key: string): [string, string] {
  const slash = key.indexOf("/");
  return slash >= 0 ? [key.slice(0, slash), key.slice(slash + 1)] : ["", key];
}

/** Split `text` on `.` from the right into at most `count` parts; the first keeps extra dots. */
function splitRight(text: string, count: number): string[] {
  const parts = text.split(".");
  if (parts.length <= count) return parts;
  const lead = parts.length - (count - 1);
  return [parts.slice(0, lead).join("."), ...parts.slice(lead)];
}

/** Which of `names` plays the dataset and which the model (the `splitKey` rule). */
export type PartRoles = { dataset: string; model: string | null };

/**
 * The dataset and model part names of a `key_parts` pattern (2 or 3 names, one `metric`),
 * else null. Of 2 names the other part is the dataset. Of 3 names a part named `dataset` is
 * the dataset and `model` the model; otherwise the first other part is the dataset and the
 * second the model. The rule of the backend's `split_score_key`.
 *
 * Examples
 * --------
 * >>> partRoles(["model", "dataset", "metric"])
 * {dataset: "dataset", model: "model"}
 * >>> partRoles(["metric", "split"])
 * {dataset: "split", model: null}
 */
export function partRoles(names?: readonly string[] | null): PartRoles | null {
  if (!names || (names.length !== 2 && names.length !== 3) || !names.includes("metric")) return null;
  const others = names.filter((n) => n !== "metric");
  if (others.length === 1) return { dataset: others[0] ?? "", model: null };
  const dataset = others.includes("dataset")
    ? "dataset"
    : others.includes("model")
      ? (others.find((n) => n !== "model") ?? "")
      : (others[0] ?? "");
  return { dataset, model: others.find((n) => n !== dataset) ?? "" };
}

/**
 * Split a score key into prefix, dataset, model and metric.
 *
 * Without `names` the part after the first `/` is split on `.`: 3+ parts are dataset (all
 * leading parts, dots kept), model, metric; 2 parts are dataset, metric; 1 part is the metric.
 * `names` are the part names from `hypothex.yaml` (`key_parts`, 2 or 3 names, one of them
 * `metric`): the key is split from the right into that many parts (the first keeps any
 * extra dots) and `partRoles` says which part is the dataset and which the model. A key
 * with fewer parts than names, or an empty part, is not split (`dataset` and `model` null,
 * `metric` the whole tail).
 *
 * Examples
 * --------
 * >>> splitKey("reported/test-a.gpt4.top10")
 * {prefix: "reported", dataset: "test-a", model: "gpt4", metric: "top10"}
 * >>> splitKey("r/gpt4.test-a.top10", ["model", "dataset", "metric"])
 * {prefix: "r", dataset: "test-a", model: "gpt4", metric: "top10"}
 */
export function splitKey(key: string, names?: readonly string[] | null): KeyParts {
  const [prefix, tail] = prefixAndTail(key);
  const whole: KeyParts = { prefix, dataset: null, model: null, metric: tail };
  const roles = partRoles(names);
  if (names && roles) {
    const parts = splitRight(tail, names.length);
    if (parts.length !== names.length || parts.some((p) => p === "")) return whole;
    const byName = new Map(names.map((name, i) => [name, parts[i] ?? ""]));
    return {
      prefix,
      dataset: byName.get(roles.dataset) ?? null,
      model: roles.model === null ? null : (byName.get(roles.model) ?? null),
      metric: byName.get("metric") ?? tail,
    };
  }
  const parts = tail.split(".");
  if (parts.length >= 3) {
    return { prefix, dataset: parts.slice(0, -2).join("."), model: parts[parts.length - 2] ?? null, metric: parts[parts.length - 1] ?? tail };
  }
  if (parts.length === 2) return { prefix, dataset: parts[0] ?? null, model: null, metric: parts[1] ?? tail };
  return whole;
}

/** Section (metric) and panel title of one key: `splitKey`'s metric, title dataset · model. */
function place(key: string, names?: readonly string[] | null): { metric: string; title: string } {
  const { prefix, dataset, model, metric } = splitKey(key, names);
  if (dataset === null) return { metric: prefix || metric, title: metric };
  return { metric, title: model === null ? dataset : `${dataset} · ${model}` };
}

/**
 * Group score keys into sections, one per metric, the primary key's section first.
 *
 * Keys are split by `splitKey` with the task's part names (`key_parts`): the section is
 * the metric part, the panel title the dataset and model parts joined with ` · `. Keys
 * that do not split: the section is the prefix before `/` (or the key), the title the
 * part after `/`. Sections keep first-seen order after the primary's; inside a section the
 * primary key comes first, then panels by title.
 *
 * Examples
 * --------
 * >>> sectionsFromKeys(["r/a.m.top1", "r/b.m.top1"], "r/b.m.top1")
 * [{metric: "top1", panels: [{key: "r/b.m.top1", title: "b · m"}, {key: "r/a.m.top1", title: "a · m"}]}]
 * >>> sectionsFromKeys(["r/top1.a"], "r/top1.a", ["metric", "dataset"])
 * [{metric: "top1", panels: [{key: "r/top1.a", title: "a"}]}]
 */
export function sectionsFromKeys(keys: readonly string[], primary: string, names?: readonly string[] | null): KeySection[] {
  const sections = new Map<string, { key: string; title: string }[]>();
  for (const key of new Set(keys)) {
    const { metric, title } = place(key, names);
    const list = sections.get(metric) ?? [];
    list.push({ key, title });
    sections.set(metric, list);
  }
  const first = place(primary, names).metric;
  const order = [...sections.keys()];
  if (sections.has(first)) order.sort((a, b) => Number(b === first) - Number(a === first));
  return order.map((metric) => ({
    metric,
    panels: (sections.get(metric) ?? []).sort(
      (a, b) => Number(b.key === primary) - Number(a.key === primary) || a.title.localeCompare(b.title) || a.key.localeCompare(b.key),
    ),
  }));
}
