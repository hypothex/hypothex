import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { yaml } from "@codemirror/lang-yaml";
import { type Diagnostic, lintGutter, setDiagnostics } from "@codemirror/lint";
import { EditorState, type Text } from "@codemirror/state";
import { EditorView, keymap, lineNumbers } from "@codemirror/view";
import { type Ref, useEffect, useImperativeHandle, useRef } from "react";
import type { ValidationIssue as ApiValidationIssue } from "../api/models";

/** One problem reported by `POST views/validate` (contract 1.4); `suggestion` may be left out. */
export type ValidationIssue = Omit<ApiValidationIssue, "suggestion"> & { suggestion?: string | null };

/** A text change planned against the editor text (character offsets, 1-based `line`). */
export interface Insertion {
  from: number;
  to: number;
  insert: string;
  /** Line (1-based, in the new text) to put the cursor on after the change. */
  line: number;
}

/** One `- type: ...` item of the view's `panels:` list. Lines are 1-based, inclusive. */
export interface PanelOutline {
  index: number;
  title: string;
  startLine: number;
  endLine: number;
}

/** Where the `panels:` list sits in a view's YAML text. */
export interface ViewOutline {
  /** Line of the top-level `panels:` key, or null when there is none. */
  panelsLine: number | null;
  /** True when the key is written as the flow form `panels: []`. */
  emptyList: boolean;
  /** Indent of the list's `- ` markers ("  " when the list has no items yet). */
  itemIndent: string;
  /** First line after the list (lines.length + 1 when the list runs to the end). */
  endLine: number;
  panels: PanelOutline[];
}

const PANELS_KEY = /^panels:\s*(\[\s*\])?\s*(#.*)?$/;

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

function isContent(line: string): boolean {
  const t = line.trim();
  return t !== "" && !t.startsWith("#");
}

function cleanScalar(raw: string): string {
  const noComment = raw.replace(/\s+#.*$/, "").trim();
  const quoted = /^(["'])(.*)\1$/.exec(noComment);
  return quoted ? quoted[2] : noComment;
}

/**
 * Find the `panels:` list and its items in view YAML by indentation.
 *
 * The scan is textual, so it also works while the YAML is invalid. It only
 * understands the block form written by the editor and by `hx view init`.
 */
export function outlineView(text: string): ViewOutline {
  const lines = text.split("\n");
  const keyIdx = lines.findIndex((l) => PANELS_KEY.test(l));
  if (keyIdx === -1) {
    return { panelsLine: null, emptyList: false, itemIndent: "  ", endLine: lines.length + 1, panels: [] };
  }
  const emptyList = /\[\s*\]/.test(lines[keyIdx].replace(/#.*$/, ""));
  const first = lines.slice(keyIdx + 1).find(isContent);
  const firstItem = first !== undefined && /^\s*- /.test(first) ? first : undefined;
  const itemIndent = firstItem === undefined ? "  " : " ".repeat(indentOf(firstItem));
  let end = lines.length;
  for (let i = keyIdx + 1; i < lines.length; i++) {
    const l = lines[i];
    if (!isContent(l) || indentOf(l) > 0) continue;
    if (itemIndent === "" && l.startsWith("-")) continue;
    end = i;
    break;
  }
  const starts: number[] = [];
  if (!emptyList) {
    for (let i = keyIdx + 1; i < end; i++) {
      if (lines[i].startsWith(`${itemIndent}- `) || lines[i] === `${itemIndent}-`) starts.push(i);
    }
  }
  const keyIndent = itemIndent.length + 2;
  const panels = starts.map((s, index) => {
    const stop = index + 1 < starts.length ? starts[index + 1] : end;
    let title = "";
    for (let i = s; i < stop; i++) {
      const m = /^(\s*(?:-\s+)?)title:(.*)$/.exec(lines[i]);
      if (m && m[1].length === keyIndent) {
        title = cleanScalar(m[2]);
        break;
      }
    }
    return { index, title, startLine: s + 1, endLine: stop };
  });
  return { panelsLine: keyIdx + 1, emptyList, itemIndent, endLine: end + 1, panels };
}

/** Return the panel whose lines contain `line` (1-based), or null. */
export function panelAtLine(outline: ViewOutline, line: number): PanelOutline | null {
  return outline.panels.find((p) => line >= p.startLine && line <= p.endLine) ?? null;
}

/** The name in a backend message: `unknown metric route_length`, `unknown scale zzz; ...`. */
const UNKNOWN_NAME = /^unknown (?:metric|key|field|\w+) ([^\s;,]+)/;
/** Characters of a reference: `route_len@v1/median`, `usage.usd`, `macro-f1`. */
const REF_CHAR = /[\w@./-]/;
/** Characters that continue a name, so `x` is not found inside `xy`. */
const NAME_CHAR = /[\w-]/;

/**
 * Find `name` in `text` as a whole token and widen it over the rest of its reference
 * (`route_length` in `y: route_length@v1/median` covers `route_length@v1/median`).
 */
function findRef(text: string, name: string): { at: number; end: number } | null {
  for (let at = text.indexOf(name); at >= 0; at = text.indexOf(name, at + 1)) {
    if (at > 0 && REF_CHAR.test(text.charAt(at - 1))) continue;
    let end = at + name.length;
    if (end < text.length && NAME_CHAR.test(text.charAt(end))) continue;
    while (end < text.length && REF_CHAR.test(text.charAt(end))) end++;
    return { at, end };
  }
  return null;
}

/**
 * Turn validation issues into CodeMirror diagnostics.
 *
 * The name after `unknown <word> ` in the message (the backend sends it unquoted:
 * `unknown metric route_length`) narrows the mark to that reference in the line, widened
 * over its `@version/key` suffix, and a suggestion (for a metric, the whole corrected
 * reference) becomes a one-click "use X" fix that replaces the marked reference. Issues
 * without a line mark line 1; lines past the end mark the last line.
 */
export function issuesToDiagnostics(doc: Text, issues: ValidationIssue[]): Diagnostic[] {
  return issues.map((issue) => {
    const n = Math.min(Math.max(issue.line ?? 1, 1), doc.lines);
    const line = doc.line(n);
    const name = UNKNOWN_NAME.exec(issue.message)?.[1];
    const ref = name ? findRef(line.text, name) : null;
    const at = ref ? ref.at : -1;
    const lead = indentOf(line.text);
    const from = ref ? line.from + ref.at : line.from + lead;
    const to = ref ? line.from + ref.end : line.to;
    const suggestion = issue.suggestion ?? null;
    const diagnostic: Diagnostic = {
      from,
      to,
      severity: "error",
      message: issue.path ? `${issue.message} (${issue.path})` : issue.message,
    };
    if (suggestion && at >= 0) {
      diagnostic.actions = [
        {
          name: `use ${suggestion}`,
          apply: (view, a, b) => view.dispatch({ changes: { from: a, to: b, insert: suggestion } }),
        },
      ];
    }
    return diagnostic;
  });
}

/** Imperative handle: the palette and status bar drive the editor through it. */
export interface YamlEditorHandle {
  /** Apply a change planned from the current text and cursor line, then focus. */
  applyInsertion(plan: (text: string, cursorLine: number) => Insertion): void;
  /** Move the cursor to a 1-based line and scroll it into view. */
  goToLine(line: number): void;
  /** The live CodeMirror view (null before mount). */
  view(): EditorView | null;
}

export interface YamlEditorProps {
  value: string;
  onChange: (text: string) => void;
  issues: ValidationIssue[];
  onCursorLine?: (line: number) => void;
  ref?: Ref<YamlEditorHandle>;
}

const theme = EditorView.theme({
  "&": { backgroundColor: "var(--paper-2)", color: "var(--ink)", fontSize: "12px" },
  ".cm-content": { fontFamily: "var(--mono)", lineHeight: "20px" },
  ".cm-gutters": { backgroundColor: "var(--paper-2)", color: "var(--ink-3)", border: "none" },
  ".cm-lintRange-error": { textDecoration: "underline wavy var(--fail)" },
  "&.cm-focused": { outline: "none" },
});

/** CodeMirror 6 YAML editor with validation markers in the gutter and inline. */
export function YamlEditor({ value, onChange, issues, onCursorLine, ref }: YamlEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const onCursorRef = useRef(onCursorLine);
  onChangeRef.current = onChange;
  onCursorRef.current = onCursorLine;

  // Mount once; later `value` changes sync through the next effect.
  useEffect(() => {
    const view = new EditorView({
      parent: host.current as HTMLDivElement,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          lintGutter(),
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          yaml(),
          theme,
          EditorView.updateListener.of((u) => {
            if (u.docChanged) onChangeRef.current(u.state.doc.toString());
            if (u.docChanged || u.selectionSet) {
              const head = u.state.selection.main.head;
              onCursorRef.current?.(u.state.doc.lineAt(head).number);
            }
          }),
        ],
      }),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch(setDiagnostics(view.state, issuesToDiagnostics(view.state.doc, issues)));
  }, [issues]);

  useImperativeHandle(ref, () => ({
    applyInsertion(plan) {
      const view = viewRef.current;
      if (!view) return;
      const { state } = view;
      const cursorLine = state.doc.lineAt(state.selection.main.head).number;
      const change = plan(state.doc.toString(), cursorLine);
      view.dispatch({ changes: { from: change.from, to: change.to, insert: change.insert } });
      const target = view.state.doc.line(Math.min(change.line, view.state.doc.lines));
      view.dispatch({ selection: { anchor: target.to }, scrollIntoView: true });
      view.focus();
    },
    goToLine(line) {
      const view = viewRef.current;
      if (!view) return;
      const target = view.state.doc.line(Math.min(Math.max(line, 1), view.state.doc.lines));
      view.dispatch({ selection: { anchor: target.from }, scrollIntoView: true });
      view.focus();
    },
    view: () => viewRef.current,
  }));

  return <div className="hx-ed-cm" ref={host} data-testid="yaml-editor" />;
}
