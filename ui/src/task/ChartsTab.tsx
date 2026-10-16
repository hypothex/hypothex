/**
 * Charts tab (spec 4.2): the runs sidebar and the panel area. Toolbar: panel search,
 * smoothing (EMA, value shown), x axis, seeds, `+ Panel`, `Save as view`. Sections:
 * Compare (keys with two or more datasets), Scores, Step metrics (one per prefix), Score
 * keys (more than one key), then the kind's preset panels. Every panel draws the visible
 * identities in their colours and follows the sidebar's hover.
 */
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import type { Leaderboard, PanelSpec, TaskRuns } from "../api/models";
import { useSaveView } from "../api/queries";
import { EmptyState } from "../chrome/EmptyState";
import { FilterField } from "../chrome/FilterField";
import { PanelSection } from "../chrome/PanelSection";
import { colorFor } from "../lib/color";
import { hrefs, useNavigateHref } from "../pages/components/links";
import { ErrorBox } from "../pages/components/QueryState";
import { isViewName } from "../pages/ViewEditor";
import { ComparePanel } from "./ComparePanel";
import { type CompareColumn, type CompareState, compareModel, comparePanelSpec, compareTitles, defaultCompare } from "./compareModel";
import { useHighlight } from "./highlight";
import { KindSection } from "./KindSection";
import { RunsSidebar } from "./RunsSidebar";
import { stepMetricPanels, viewYaml } from "./saveView";
import { ScoreKeySections } from "./ScoreKeySections";
import { ScoresSection } from "./ScoresSection";
import { StepMetricsSection, useStepCurves } from "./StepMetricsSection";
import { type SeedsMode, type XMode, hasTime, matchesSearch, metricSections, stepMetrics } from "./stepMetrics";
import { type Selection, listIdentities } from "./useRunSelection";

export interface ChartsTabProps {
  project: string;
  task: string;
  data: TaskRuns;
  board: Leaderboard | undefined;
  selection: Selection;
  onSelection: (patch: Partial<Selection>) => void;
  onOpenRun: (runId: string) => void;
  /** Open a saved view's tab (after Save as view). */
  onOpenView: (name: string) => void;
  /** Names already used by views of the task (Save as view must not overwrite one). */
  viewNames: readonly string[];
}

export interface AddPanelItem {
  label: string;
  onPick: () => void;
  disabled?: boolean;
}

export function ChartsTab(props: ChartsTabProps): ReactElement {
  const { project, task, data, board, selection, onSelection, onOpenRun, onOpenView, viewNames } = props;
  const [query, setQuery] = useState("");
  const [smoothing, setSmoothing] = useState(0.6);
  const [x, setX] = useState<XMode>("step");
  const [seeds, setSeeds] = useState<SeedsMode>("mean");
  const [saving, setSaving] = useState(false);
  const highlight = useHighlight();
  const navigate = useNavigateHref();
  const items = listIdentities(selection, data).filter((i) => !i.hidden);
  const order = items.map((i) => i.id);
  const colorOf = (id: string): string => colorFor(id, order);
  const cmp = useMemo(() => compareModel(data.score_keys, data.primary, data.key_parts), [data.score_keys, data.primary, data.key_parts]);
  const [compares, setCompares] = useState<CompareState[] | null>(null);
  const compareList = cmp ? (compares ?? [defaultCompare(cmp, data.primary, data.key_parts)]) : [];
  const addCompare = (): void => {
    if (cmp) setCompares([...compareList, defaultCompare(cmp, data.primary, data.key_parts)]);
  };
  const columns: CompareColumn[] = items.map((i) => ({
    id: i.id,
    name: i.name,
    color: colorOf(i.id),
    scores: i.kind === "group" && i.group ? i.group.scores : (i.runs[0]?.scores ?? {}),
  }));
  const compareNames = cmp ? compareTitles(compareList, cmp.labels) : [];
  const shownCompares = compareList
    .map((state, index) => ({ state, index, title: compareNames[index] ?? "" }))
    .filter(({ title }) => matchesSearch(title, query));
  const names = stepMetrics(data.metric_names);
  const sections = metricSections(names);
  const curves = useStepCurves(project, task, names, items);
  const timed = hasTime(curves.points);
  const seedWord = data.kind === "system_bench" ? "Repeats" : "Seeds";
  const addView = (): void => navigate(hrefs.edit(project, task, "new"));
  const savedPanels: PanelSpec[] = [
    ...(cmp ? shownCompares.map(({ state, title }) => comparePanelSpec(state, cmp.labels, title)) : []),
    ...stepMetricPanels(sections, query),
  ];
  return (
    <div className="ws">
      <RunsSidebar data={data} selection={selection} onChange={onSelection} onOpen={onOpenRun} />
      <div className="panels">
        <div className="ptools">
          <FilterField value={query} onChange={setQuery} placeholder="Search panels" label="Search panels" size="sm" />
          {names.length > 0 ? (
            <>
              <label>
                Smoothing
                <input
                  type="range"
                  className="ctl"
                  min={0}
                  max={0.95}
                  step={0.05}
                  value={smoothing}
                  aria-label="Smoothing"
                  onChange={(e) => setSmoothing(Number(e.target.value))}
                />
                <span className="val">{smoothing.toFixed(2)}</span>
              </label>
              <label>
                X
                <select className="ctl" aria-label="X axis" value={x} onChange={(e) => setX(e.target.value as XMode)}>
                  <option value="step">step</option>
                  <option value="wall" disabled={!timed}>
                    wall time
                  </option>
                  <option value="relative" disabled={!timed}>
                    relative time
                  </option>
                </select>
              </label>
              <label>
                {seedWord}
                <select className="ctl" aria-label={seedWord} value={seeds} onChange={(e) => setSeeds(e.target.value as SeedsMode)}>
                  <option value="mean">mean</option>
                  <option value="band">mean + band</option>
                  <option value="each">{seedWord === "Repeats" ? "each repeat" : "each seed"}</option>
                </select>
              </label>
            </>
          ) : null}
          <span className="pbtns">
            <AddPanelMenu
              items={[
                { label: "Compare", onPick: addCompare, disabled: cmp === null },
                { label: "Custom view…", onPick: addView },
              ]}
            />
            <button type="button" className="btn sm" aria-expanded={saving} onClick={() => setSaving((s) => !s)}>
              Save as view
            </button>
          </span>
        </div>
        {saving ? (
          <SaveViewForm
            project={project}
            task={task}
            panels={savedPanels}
            taken={viewNames}
            onSaved={(name) => {
              setSaving(false);
              onOpenView(name);
            }}
            onCancel={() => setSaving(false)}
          />
        ) : null}
        {items.length === 0 ? (
          <EmptyState title={data.runs.length === 0 ? "No runs yet" : "No runs shown"} />
        ) : (
          <>
            {cmp && shownCompares.length > 0 ? (
              <PanelSection title="Compare" count={shownCompares.length} storageKey={`${project}/${task}`} grid="wide">
                {shownCompares.map(({ state, index, title }) => (
                  <ComparePanel
                    key={index}
                    title={title}
                    model={cmp}
                    state={state}
                    columns={columns}
                    higherIsBetter={data.higher_is_better}
                    onState={(next) => setCompares(compareList.map((s, j) => (j === index ? next : s)))}
                    onRemove={index > 0 ? () => setCompares(compareList.filter((_, j) => j !== index)) : undefined}
                  />
                ))}
              </PanelSection>
            ) : null}
            <ScoresSection data={data} items={items} colorOf={colorOf} highlight={highlight} query={query} />
            <StepMetricsSection
              curves={curves}
              sections={sections}
              items={items}
              colorOf={colorOf}
              highlight={highlight}
              query={query}
              smoothing={smoothing}
              x={x}
              seeds={seeds}
              storageKey={`${project}/${task}`}
              onAddPanel={addView}
            />
            {data.score_keys.length > 1 ? (
              <ScoreKeySections data={data} items={items} colorOf={colorOf} highlight={highlight} query={query} />
            ) : null}
          </>
        )}
        <KindSection project={project} task={task} kind={data.kind} board={board} query={query} />
      </div>
    </div>
  );
}

/** `+ Panel`: a menu of panels to add; Escape or a press outside closes it. */
export function AddPanelMenu({ items }: { items: readonly AddPanelItem[] }): ReactElement {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: globalThis.MouseEvent): void => {
      if (!anchor.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  return (
    <span className="popover-anchor add-panel" ref={anchor}>
      <button ref={button} type="button" className="btn sm" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        + Panel
      </button>
      {open ? (
        <div
          className="popover"
          role="menu"
          aria-label="Add panel"
          onKeyDown={(e) => {
            if (e.key !== "Escape") return;
            e.stopPropagation();
            setOpen(false);
            button.current?.focus();
          }}
        >
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              disabled={it.disabled}
              onClick={() => {
                setOpen(false);
                it.onPick();
              }}
            >
              {it.label}
            </button>
          ))}
        </div>
      ) : null}
    </span>
  );
}

interface SaveViewFormProps {
  project: string;
  task: string;
  panels: readonly PanelSpec[];
  taken: readonly string[];
  onSaved: (name: string) => void;
  onCancel: () => void;
}

/** Name the new view (a free, valid view name) and store the shown panels as it. */
function SaveViewForm({ project, task, panels, taken, onSaved, onCancel }: SaveViewFormProps): ReactElement {
  const [name, setName] = useState("");
  const save = useSaveView(project, task);
  const exists = taken.includes(name);
  const ok = isViewName(name) && !exists && panels.length > 0;
  return (
    <form
      className="save-view"
      aria-label="Save as view"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ok || save.isPending) return;
        save.mutate({ name, text: viewYaml({ title: name, panels: [...panels] }) }, { onSuccess: () => onSaved(name) });
      }}
    >
      <input aria-label="View name" value={name} placeholder="view_name" spellCheck={false} onChange={(e) => setName(e.target.value.trim())} />
      <span className="muted">{exists ? `${name} exists` : `${panels.length} panel${panels.length === 1 ? "" : "s"}`}</span>
      <button type="submit" className="btn sm primary" disabled={!ok || save.isPending}>
        Save
      </button>
      <button type="button" className="btn sm" onClick={onCancel}>
        Cancel
      </button>
      {save.error ? <ErrorBox error={save.error} /> : null}
    </form>
  );
}
