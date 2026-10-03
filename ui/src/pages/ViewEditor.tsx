import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import "../editor/editor.css";
import { ApiError, api } from "../api/client";
import type { ViewSpec } from "../api/models";
import { useLeaderboard, useSaveView, useView, useViewQuery, useViews } from "../api/queries";
import { PanelPalette, type PanelType, panelSnippet, planInsert } from "../editor/PanelPalette";
import { type LayoutHint, type PanelResult, Preview } from "../editor/Preview";
import {
  outlineView,
  panelAtLine,
  type ValidationIssue,
  YamlEditor,
  type YamlEditorHandle,
} from "../editor/YamlEditor";
import { shellJoin } from "./components/format";
import { PanelBody } from "./components/PanelGrid";

/** Starting text for `/t/:project/:task/edit/new`. */
export const NEW_VIEW_TEXT = "title: new view\npanels: []\n";

const VIEW_NAME = /^[a-z0-9][a-z0-9_-]*$/;

/** True for a name `PUT views/{name}` accepts (contract 1.4; `overview` is reserved). */
export function isViewName(name: string): boolean {
  return VIEW_NAME.test(name) && name !== "overview";
}

/** Metric name from a task primary such as `accuracy/value` (the snippet default). */
export function metricOf(primary: string): string {
  return primary.split("/")[0] || "metric";
}

/**
 * Shell text that saves `text` as view `name` with the CLI.
 *
 * `hx view add` reads a file, so the command writes one with a quoted heredoc
 * (no shell expansion inside) and then adds it. `project` and `task` come from the
 * URL, so every argument is shell-quoted.
 */
export function cliCommand(project: string, task: string, name: string, text: string): string {
  const body = text.endsWith("\n") ? text : `${text}\n`;
  const lines = new Set(body.split("\n"));
  let tag = "YAML";
  while (lines.has(tag)) tag = `${tag}_`;
  const file = `/tmp/hx-view-${name}.yaml`;
  const add = shellJoin(["hx", "view", "add", task, "--file", file, "--name", name, "-p", project]);
  return `cat > ${shellJoin([file])} <<'${tag}'\n${body}${tag}\n${add}`;
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

function registryPanel(result: PanelResult): ReactNode {
  return <PanelBody result={result} />;
}

export interface ViewEditorProps {
  project: string;
  task: string;
  /** View name from the route; `new` starts a blank view. */
  view: string;
  /** Called with the saved name after every successful Save. */
  onSaved?: (name: string) => void;
  /** Renders one preview panel; defaults to the `ui/src/panels` registry. */
  renderPanel?: (result: PanelResult) => ReactNode;
}

/** `/t/:project/:task/edit/:view`: YAML on the left, live preview on the right. */
export function ViewEditor({ project, task, view, onSaved, renderPanel = registryPanel }: ViewEditorProps) {
  const isNew = view === "new";
  const nameEditable = isNew || view === "overview";
  const editor = useRef<YamlEditorHandle>(null);

  const [loaded, setLoaded] = useState(isNew);
  const [baseline, setBaseline] = useState(isNew ? NEW_VIEW_TEXT : "");
  const [text, setText] = useState(baseline);
  const [name, setName] = useState(nameEditable ? "" : view);
  const [cursorLine, setCursorLine] = useState(1);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [good, setGood] = useState<ViewSpec | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const doc = useView(project, task, isNew ? null : view);
  useEffect(() => {
    if (loaded || !doc.data) return;
    setBaseline(doc.data.text);
    setText(doc.data.text);
    setLoaded(true);
  }, [doc.data, loaded]);

  // A new name must not overwrite a view that is already there (PUT replaces the file).
  const views = useViews(project, task);
  const board = useLeaderboard(project, task);
  const metric = board.data ? metricOf(board.data.primary) : "metric";

  const debounced = useDebounced(text, 300);
  const validation = useQuery({
    queryKey: ["views", "validate", project, task, debounced],
    queryFn: ({ signal }) => api.validateView(project, task, debounced, signal),
    enabled: loaded && debounced === text,
    staleTime: Number.POSITIVE_INFINITY,
  });
  useEffect(() => {
    if (!validation.data) return;
    setIssues(validation.data.issues);
    if (validation.data.ok && validation.data.view) setGood(validation.data.view);
  }, [validation.data]);

  const preview = useViewQuery(project, task, good ? { view: good } : null);
  // `POST views/validate` returns the view resolved (contract 2): `from:` preset panels,
  // with their layouts, are already in `good.panels`, for any preset kind.
  const resolved = good?.panels ?? [];

  const checking = !loaded || debounced !== text || validation.isFetching || !validation.data;
  const valid = !checking && validation.data?.ok === true;
  const invalid = !checking && validation.data?.ok === false;
  const dirty = text !== baseline;

  const save = useSaveView(project, task);
  const onSave = () => {
    const sent = text;
    save.mutate(
      { name, text: sent },
      {
        onSuccess: () => {
          setBaseline(sent);
          setSaveError(null);
          onSaved?.(name);
        },
        onError: (err) => {
          setSaveError(err.message);
          if (err instanceof ApiError && err.issues.length > 0) setIssues(err.issues);
        },
      },
    );
  };

  const outline = useMemo(() => outlineView(text), [text]);
  const results = preview.data?.panels ?? [];
  const indexOfTitle = (title: string) => results.findIndex((r) => r.title === title);
  const layouts: LayoutHint[] = results.map(
    (r) => resolved.find((p) => (p.title ?? "") === r.title)?.layout ?? {},
  );
  const cursorPanel = panelAtLine(outline, cursorLine);
  const selected = cursorPanel ? indexOfTitle(cursorPanel.title) : -1;
  const problems: Record<number, string> = {};
  for (const issue of issues) {
    const panel = issue.line === null ? null : panelAtLine(outline, issue.line);
    const i = panel ? indexOfTitle(panel.title) : -1;
    if (i >= 0 && problems[i] === undefined) problems[i] = `${issue.message}, ln ${issue.line}`;
  }

  const nameOk = isViewName(name);
  const listed = !nameEditable || views.data !== undefined;
  const taken = nameEditable && (views.data?.some((v) => v.name === name) ?? false);
  const canSave = valid && nameOk && listed && !taken && (dirty || nameEditable) && !save.isPending;
  const saveTitle = invalid
    ? `Fix ${issues.length} error${issues.length === 1 ? "" : "s"} to save`
    : !nameOk
      ? "Name: a-z, 0-9, _ or -, not overview"
      : taken
        ? `${name} exists: open it to edit`
        : !listed
          ? views.error
            ? `Cannot list views: ${views.error.message}`
            : "Checking the names in use"
          : `Validate, then write .hypothex/views/${task}/${name}.yaml`;
  const cli = nameOk ? cliCommand(project, task, name, text) : "";

  const onInsert = (type: PanelType) => {
    editor.current?.applyInsertion((current, line) => planInsert(current, line, panelSnippet(type, metric)));
  };
  const onEdit = (next: string) => {
    setText(next);
    setSaveError(null);
  };
  const onDiscard = () => {
    setText(baseline);
    setSaveError(null);
  };
  const onCopy = async () => {
    await navigator.clipboard.writeText(cli);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const onSelectPanel = (index: number) => {
    const panel = outline.panels.find((p) => p.title === results[index]?.title);
    if (panel) editor.current?.goToLine(panel.startLine);
  };

  const firstIssueLine = issues.find((i) => i.line !== null)?.line ?? null;
  const nPanels = resolved.length;
  let status: ReactNode;
  if (validation.error) status = <span className="vs err">✕ {validation.error.message}</span>;
  else if (checking) status = <span className="vs">checking</span>;
  else if (invalid)
    status = (
      <span className="vs err">
        ✕ {issues.length} error{issues.length === 1 ? "" : "s"}
        {firstIssueLine !== null && (
          <button type="button" onClick={() => editor.current?.goToLine(firstIssueLine)}>
            ln {firstIssueLine}
          </button>
        )}
      </span>
    );
  else status = <span className="vs ok">{`✓ valid · ${nPanels} panel${nPanels === 1 ? "" : "s"}`}</span>;

  const heading = isNew ? "New view" : `Edit ${good?.title ?? view}`;
  return (
    <div className="hx-ed">
      <p className="crumb">
        {project}
        <span className="sep">/</span>
        {task}
        <span className="sep">/</span>
        {isNew ? "new" : view}
      </p>
      <div className="hx-ed-top">
        <h1>
          {heading}
          {dirty && <small title="Not saved yet">● unsaved</small>}
        </h1>
        <div className="hx-ed-act">
          {nameEditable && (
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value.trim())} placeholder="route_quality" />
            </label>
          )}
          <button type="button" className="btn" disabled={!dirty} onClick={onDiscard}>
            Discard
          </button>
          <button
            type="button"
            className="btn"
            disabled={!nameOk}
            title={nameOk ? cli.split("\n").at(-1) : "Name the view first"}
            onClick={() => void onCopy()}
          >
            {copied ? "Copied" : "Copy as CLI"}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!canSave}
            title={saveTitle}
            onClick={onSave}
          >
            Save
          </button>
        </div>
      </div>
      {doc.error && <p className="hx-ed-alert" role="alert">{doc.error.message}</p>}
      {saveError && <p className="hx-ed-alert" role="alert">{saveError}</p>}
      <div className="hx-ed-split">
        <div>
          <PanelPalette onInsert={onInsert} />
          <div className="hx-ed-editor">
            <div className="hx-ed-bar" data-testid="ed-status">
              <span className="file">{`.hypothex/views/${task}/${name || "<name>"}.yaml`}</span>
              {status}
            </div>
            <YamlEditor ref={editor} value={text} onChange={onEdit} issues={issues} onCursorLine={setCursorLine} />
          </div>
        </div>
        <Preview
          results={results}
          layouts={layouts}
          selected={selected >= 0 ? selected : null}
          problems={problems}
          stale={invalid}
          renderPanel={renderPanel}
          onSelect={onSelectPanel}
        />
      </div>
    </div>
  );
}

export default ViewEditor;
