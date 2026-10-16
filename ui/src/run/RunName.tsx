/**
 * A run's name with inline rename (spec 5.2): the name, a pencil to rename, and while
 * editing an input with Save, Cancel and, for a renamed run, Reset name. Enter saves,
 * Escape cancels. The new name shows at once and goes back if the server refuses it.
 * With `runIds` (a config of several seeds) each of those runs is renamed (spec 5.2).
 */
import { type KeyboardEvent, type ReactElement, useEffect, useRef, useState } from "react";
import type { RunRecord, TaskRun } from "../api/models";
import { useRenameRun } from "../api/queries";
import { Icon } from "../chrome/Icon";
import { firstClause, shortId } from "../pages/components/format";
import "./run.css";

/** Longest name the API takes (spec 5.2). */
export const MAX_NAME = 80;

/** `name · seed 2` (run views); the name alone for a run without a seed. */
export function withSeed(name: string, seed: number | null | undefined): string {
  return seed === null || seed === undefined ? name : `${name} · seed ${seed}`;
}

export interface RunTitle {
  /** What the run is called now. */
  display: string;
  /** The derived name in the same form; Reset name restores it. */
  derived: string;
  renamed: boolean;
}

/**
 * The run views' name: a rename as typed, else the derived name with its seed. Without
 * the task's runs (no task, or still loading): the record's own name, else the first
 * clause of the hypothesis, else the short id, with the seed.
 */
export function runTitle(
  run: Pick<TaskRun, "name" | "derived_name" | "renamed" | "seed"> | null,
  record: Pick<RunRecord, "run_id" | "hypothesis" | "seed" | "name">,
): RunTitle {
  if (run) {
    const derived = withSeed(run.derived_name, run.seed);
    return run.renamed ? { display: run.name, derived, renamed: true } : { display: derived, derived, renamed: false };
  }
  const derived = withSeed(firstClause(record.hypothesis, `run ${shortId(record.run_id)}`), record.seed);
  const own = record.name?.trim();
  return own ? { display: own, derived, renamed: true } : { display: derived, derived, renamed: false };
}

/** Why `text` cannot be a name, or null (an empty text is a reset, not a problem). */
export function nameProblem(text: string): string | null {
  if (/[\r\n]/.test(text)) return "One line only";
  if (text.trim().length > MAX_NAME) return `At most ${MAX_NAME} characters`;
  return null;
}

/** The name to send: null resets (empty, or the derived name typed back). */
export function nameToSend(typed: string, derived: string): string | null {
  const v = typed.trim();
  return v === "" || v === derived ? null : v;
}

export interface RunNameProps {
  runId: string;
  /** Rename each of these runs instead of `runId` alone (a config: every run of the group). */
  runIds?: readonly string[];
  display: string;
  derived: string;
  renamed: boolean;
  /** What on the text starts editing: "click" (run header) or "dblclick" (list rows). The pencil always does. */
  editOn?: "click" | "dblclick";
  className?: string;
}

interface Shown {
  display: string;
  renamed: boolean;
}

export function RunName({ runId, runIds, display, derived, renamed, editOn = "click", className }: RunNameProps): ReactElement {
  const rename = useRenameRun();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(display);
  const [shown, setShown] = useState<Shown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  // new server data replaces the optimistic name (adjusted while rendering, not in an effect)
  const [seen, setSeen] = useState<Shown>({ display, renamed });
  if (seen.display !== display || seen.renamed !== renamed) {
    setSeen({ display, renamed });
    setShown(null);
  }
  useEffect(() => {
    if (!editing) return;
    input.current?.focus();
    input.current?.select();
  }, [editing]);
  const current: Shown = shown ?? { display, renamed };
  const cls = (extra: string) => ["run-name", extra, className].filter(Boolean).join(" ");

  const start = () => {
    setText(current.display);
    setError(null);
    setEditing(true);
  };
  const cancel = () => {
    setEditing(false);
    setError(null);
  };
  const send = (name: string | null) => {
    const before = current;
    setShown(name === null ? { display: derived, renamed: false } : { display: name, renamed: true });
    setEditing(false);
    setError(null);
    const ids = runIds && runIds.length > 0 ? runIds : [runId];
    void (async () => {
      try {
        // one at a time: a refused run stops the rest
        for (const id of ids) await rename.mutateAsync({ runId: id, name });
      } catch (err) {
        setShown(before);
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  };
  const save = () => {
    const problem = nameProblem(text);
    if (problem) {
      setError(problem);
      return;
    }
    const name = nameToSend(text, derived);
    const unchanged = name === null ? !current.renamed : current.renamed && name === current.display;
    if (unchanged) cancel();
    else send(name);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      save();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  };

  if (editing) {
    return (
      <span className={cls("editing")}>
        <input
          ref={input}
          className="rename"
          aria-label="Run name"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
        />
        <button type="button" className="btn sm primary" onClick={save}>
          Save
        </button>
        <button type="button" className="btn sm" onClick={cancel}>
          Cancel
        </button>
        {current.renamed ? (
          <button type="button" className="btn sm ghost" onClick={() => send(null)}>
            Reset name
          </button>
        ) : null}
        {error ? (
          <span className="rename-err" role="alert">
            {error}
          </span>
        ) : null}
      </span>
    );
  }
  const open = editOn === "click" ? { onClick: start } : { onDoubleClick: start };
  return (
    <span className={cls("")}>
      <span className="rn-t" {...open}>
        {current.display}
      </span>
      <button type="button" className="pen" aria-label="Rename" title="Rename" onClick={start}>
        <Icon name="edit" />
      </button>
      {error ? (
        <span className="rename-err" role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}
