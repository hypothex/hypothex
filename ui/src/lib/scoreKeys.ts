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

/**
 * Split a score key into prefix, dataset, model and metric.
 *
 * Without `names` the part after the first `/` is split on `.`: 3+ parts are dataset (all
 * leading parts, dots kept), model, metric; 2 parts are dataset, metric; 1 part is the metric.
 * `names` are the part names from `hypothex.yaml` (`key_parts`, 2 or 3 names, one of them
 * `metric`): the key is split from the right into that many parts (the first keeps any
 * extra dots). Of a 2-name pattern the other part is the dataset. Of a 3-name pattern a part
 * named `dataset` is the dataset and `model` the model; otherwise the first other part is
 * the dataset and the second the model. A key with fewer parts than names, or an empty
 * part, is not split (`dataset` and `model` null, `metric` the whole tail).
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
  if (names && (names.length === 2 || names.length === 3) && names.includes("metric")) {
    const parts = splitRight(tail, names.length);
    if (parts.length !== names.length || parts.some((p) => p === "")) return whole;
    const byName = new Map(names.map((name, i) => [name, parts[i] ?? ""]));
    const others = names.filter((n) => n !== "metric");
    const metric = byName.get("metric") ?? tail;
    if (others.length === 1) return { prefix, dataset: byName.get(others[0] ?? "") ?? null, model: null, metric };
    const datasetName = others.includes("dataset")
      ? "dataset"
      : others.includes("model")
        ? (others.find((n) => n !== "model") ?? "")
        : (others[0] ?? "");
    const modelName = others.find((n) => n !== datasetName) ?? "";
    return { prefix, dataset: byName.get(datasetName) ?? null, model: byName.get(modelName) ?? null, metric };
  }
  const parts = tail.split(".");
  if (parts.length >= 3) {
    return { prefix, dataset: parts.slice(0, -2).join("."), model: parts[parts.length - 2] ?? null, metric: parts[parts.length - 1] ?? tail };
  }
  if (parts.length === 2) return { prefix, dataset: parts[0] ?? null, model: null, metric: parts[1] ?? tail };
  return whole;
}

/** Section (metric) and panel title of one key. */
function place(key: string): { metric: string; title: string } {
  const [prefix, tail] = prefixAndTail(key);
  const parts = tail.split(".");
  if (parts.length >= 2) return { metric: parts[parts.length - 1] ?? tail, title: parts.slice(0, -1).join(" · ") };
  return { metric: prefix || tail, title: tail };
}

/**
 * Group score keys into sections, one per metric, the primary key's section first.
 *
 * Dotted keys: the section is the last part, the panel title the other parts joined with
 * ` · `. Keys without dots: the section is the prefix before `/` (or the key), the title the
 * part after `/`. Sections keep first-seen order after the primary's; inside a section the
 * primary key comes first, then panels by title.
 *
 * Examples
 * --------
 * >>> sectionsFromKeys(["r/a.m.top1", "r/b.m.top1"], "r/b.m.top1")
 * [{metric: "top1", panels: [{key: "r/b.m.top1", title: "b · m"}, {key: "r/a.m.top1", title: "a · m"}]}]
 */
export function sectionsFromKeys(keys: readonly string[], primary: string): KeySection[] {
  const sections = new Map<string, { key: string; title: string }[]>();
  for (const key of new Set(keys)) {
    const { metric, title } = place(key);
    const list = sections.get(metric) ?? [];
    list.push({ key, title });
    sections.set(metric, list);
  }
  const first = place(primary).metric;
  const order = [...sections.keys()];
  if (sections.has(first)) order.sort((a, b) => Number(b === first) - Number(a === first));
  return order.map((metric) => ({
    metric,
    panels: (sections.get(metric) ?? []).sort(
      (a, b) => Number(b.key === primary) - Number(a.key === primary) || a.title.localeCompare(b.title) || a.key.localeCompare(b.key),
    ),
  }));
}
