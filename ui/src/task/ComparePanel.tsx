/**
 * Compare panel (spec 4.2): datasets side by side. Controls: Datasets (multi), Model
 * (single, when keys have a model part), Metrics (multi); multi-selects keep one value.
 * Table by default: one row per dataset (grouped under metric header rows when several
 * metrics), one column per visible run; best value per row green. `Table | Bars` shows
 * grouped bars instead (one facet per metric, legend).
 */
import { Fragment, type ReactElement } from "react";
import { GroupedBars } from "../charts/BarPanel";
import { Fit } from "../charts/Fit";
import { Panel } from "../chrome/Panel";
import { Segmented } from "../chrome/Segmented";
import { fmtScore } from "../pages/components/format";
import { type CompareColumn, type CompareModel, type CompareRender, type CompareRow, type CompareState, compareRows, compareTitle, toggleKeepOne } from "./compareModel";
import "./task.css";

export interface CompareBodyProps {
  model: CompareModel;
  state: CompareState;
  onState: (next: CompareState) => void;
  columns: readonly CompareColumn[];
  higherIsBetter: boolean;
  /** Draw the Table | Bars switch inside the body (a saved view panel); the Charts tab puts it in the header. */
  showSwitch?: boolean;
}

const RENDERS = [
  ["table", "Table"],
  ["bars", "Bars"],
] as const;

function RenderSwitch({ state, onState }: Pick<CompareBodyProps, "state" | "onState">): ReactElement {
  return <Segmented label="Render" options={RENDERS} value={state.render} onChange={(render: CompareRender) => onState({ ...state, render })} />;
}

interface ChipGroupProps {
  label: string;
  values: readonly string[];
  selected: readonly string[];
  single?: boolean;
  onToggle: (value: string) => void;
}

function ChipGroup({ label, values, selected, single = false, onToggle }: ChipGroupProps): ReactElement {
  return (
    <div className="cmp-row">
      <span className="cmp-l">{label}</span>
      <div className="cmp-chips" role={single ? "radiogroup" : "group"} aria-label={label}>
        {values.map((v) => (
          <button
            key={v}
            type="button"
            className={`chip${selected.includes(v) ? " on" : ""}`}
            role={single ? "radio" : "checkbox"}
            aria-checked={selected.includes(v)}
            onClick={() => onToggle(v)}
          >
            {v}
          </button>
        ))}
      </div>
    </div>
  );
}

function CompareTable({ rows, columns, metrics }: { rows: readonly CompareRow[]; columns: readonly CompareColumn[]; metrics: readonly string[] }): ReactElement {
  const many = metrics.length > 1;
  return (
    <div className="tblwrap cmp-wrap">
      <table className="t cmp-t" aria-label="Compare table">
        <thead>
          <tr>
            <th scope="col">{many ? "Metric · dataset" : `${metrics[0] ?? ""} · dataset`}</th>
            {columns.map((c) => (
              <th key={c.id} scope="col" className="num">
                <span className="sw" style={{ background: c.color }} aria-hidden="true" />
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <Fragment key={metric}>
              {many ? (
                <tr className="g">
                  <td colSpan={columns.length + 1}>{metric}</td>
                </tr>
              ) : null}
              {rows
                .filter((r) => r.metric === metric)
                .map((r) => (
                  <tr key={`${metric}/${r.dataset}`}>
                    <th scope="row" className={many ? "in" : undefined}>
                      {r.dataset}
                    </th>
                    {r.values.map((v, i) => (
                      <td key={columns[i]?.id ?? i} className={`num${v !== null && v === r.best ? " best" : ""}`}>
                        {fmtScore(v)}
                      </td>
                    ))}
                  </tr>
                ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CompareBars({ rows, columns, metrics }: { rows: readonly CompareRow[]; columns: readonly CompareColumn[]; metrics: readonly string[] }): ReactElement {
  const index = new Map(columns.map((c, i) => [c.id, i]));
  return (
    <div>
      <div className="legend">
        {columns.map((c) => (
          <span key={c.id} className="st">
            <span className="sw" style={{ background: c.color }} aria-hidden="true" />
            {c.name}
          </span>
        ))}
      </div>
      <div className="facets" style={{ gridTemplateColumns: `repeat(${metrics.length}, minmax(0, 1fr))` }}>
        {metrics.map((metric) => {
          const mine = new Map(rows.filter((r) => r.metric === metric).map((r) => [r.dataset, r]));
          return (
            <div key={metric} className="facet">
              <div className="facet-h">{metric}</div>
              <Fit>
                {(width) => (
                  <GroupedBars
                    width={width}
                    categories={[...mine.keys()]}
                    series={columns}
                    valueOf={(dataset, seriesId) => mine.get(dataset)?.values[index.get(seriesId) ?? -1] ?? null}
                    best={(dataset) => mine.get(dataset)?.best ?? null}
                  />
                )}
              </Fit>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CompareBody({ model, state, onState, columns, higherIsBetter, showSwitch = true }: CompareBodyProps): ReactElement {
  const rows = compareRows(model, state, columns, higherIsBetter);
  const metrics = model.metrics.filter((m) => state.metrics.includes(m));
  return (
    <div className="cmp-body">
      <div className="cmp">
        <ChipGroup
          label={model.labels.datasets}
          values={model.datasets}
          selected={state.datasets}
          onToggle={(v) => onState({ ...state, datasets: toggleKeepOne(state.datasets, v, model.datasets) })}
        />
        {model.models.length > 1 ? (
          <ChipGroup single label={model.labels.model} values={model.models} selected={state.model ? [state.model] : []} onToggle={(v) => onState({ ...state, model: v })} />
        ) : null}
        <ChipGroup
          label={model.labels.metrics}
          values={model.metrics}
          selected={state.metrics}
          onToggle={(v) => onState({ ...state, metrics: toggleKeepOne(state.metrics, v, model.metrics) })}
        />
        {showSwitch ? <RenderSwitch state={state} onState={onState} /> : null}
      </div>
      {state.render === "bars" ? <CompareBars rows={rows} columns={columns} metrics={metrics} /> : <CompareTable rows={rows} columns={columns} metrics={metrics} />}
    </div>
  );
}

export function ComparePanel({ onRemove, title, ...body }: CompareBodyProps & { onRemove?: () => void; title?: string }): ReactElement {
  const shown = body.model.datasets.filter((d) => body.state.datasets.includes(d)).length;
  return (
    <Panel
      className="cmp-panel"
      title={title ?? compareTitle(body.state, body.model.labels)}
      aside={`${shown} × ${body.columns.length} runs`}
      tools={
        <span className="cmp-aside">
          <RenderSwitch state={body.state} onState={body.onState} />
          {onRemove ? (
            <button type="button" className="btn sm ghost" aria-label="Remove compare panel" onClick={onRemove}>
              Remove
            </button>
          ) : null}
        </span>
      }
    >
      <CompareBody {...body} showSwitch={false} />
    </Panel>
  );
}
