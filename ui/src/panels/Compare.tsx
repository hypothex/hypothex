/**
 * `compare` view panel (spec 4.2 "Save as view"): a saved Compare panel drawn from its
 * `views/query` rows (`{dataset, model, metric, key, run_id, group_id, name, value}`).
 * `meta.render` picks table or bars; `meta.higher_is_better` the best direction;
 * `meta.key_parts` (the task's `score_keys` names) label the controls.
 */
import { type ReactElement, useMemo, useState } from "react";
import { colorFor } from "../lib/color";
import { CompareBody } from "../task/ComparePanel";
import { type CompareResultRow, type CompareState, compareFromRows, compareLabels } from "../task/compareModel";
import type { PanelProps } from "./index";

const stringList = (v: unknown): string[] | null => (Array.isArray(v) && v.every((x) => typeof x === "string") ? v : null);

export function ComparePanelResult({ result }: PanelProps): ReactElement {
  const built = useMemo(() => compareFromRows(result.rows as unknown as CompareResultRow[]), [result.rows]);
  const [state, setState] = useState<CompareState | null>(null);
  if (!built) return <p className="panel-empty">No compare rows</p>;
  const order = built.columns.map((c) => c.id);
  const columns = built.columns.map((c) => ({ ...c, color: colorFor(c.id, order) }));
  const render = result.meta?.render === "bars" ? "bars" : "table";
  const model = { ...built.model, labels: compareLabels(stringList(result.meta?.key_parts)) };
  return (
    <CompareBody
      model={model}
      state={state ?? { ...built.state, render }}
      onState={setState}
      columns={columns}
      higherIsBetter={() => result.meta?.higher_is_better !== false}
    />
  );
}
