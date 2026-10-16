/**
 * A run's name with inline rename (spec 5.2): the name, a pencil to rename, and while
 * editing an input with Save, Cancel and, for a renamed run, Reset name. Enter saves,
 * Escape cancels. The new name shows at once and goes back if the server refuses it.
 * With `runs` (a config of several seeds) each of those runs is renamed (spec 5.2), all or
 * none: a refusal puts the runs already renamed back to their old names (`renameEach`).
 */
import { type KeyboardEvent, type ReactElement, useEffect, useRef, useState } from "react";
import type { RunRecord, TaskRun } from "../api/models";
import { auth } from "../api/auth";
import { hasScope } from "../api/scopes";
import { useMe, useRenameRun } from "../api/queries";
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

/** Every line boundary of Python's `str.splitlines`, the hub's one-line check. */
const LINE_BREAK = /[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/;

/** Why `text` cannot be a name, or null (an empty text is a reset, not a problem). */
export function nameProblem(text: string): string | null {
  if (LINE_BREAK.test(text)) return "One line only";
  if (text.trim().length > MAX_NAME) return `At most ${MAX_NAME} characters`;
  return null;
}

/** The name to send: null resets (empty, or the derived name typed back). */
export function nameToSend(typed: string, derived: string): string | null {
  const v = typed.trim();
  return v === "" || v === derived ? null : v;
}

/** A run to rename and the name it has now: its rename, or null (it shows its derived name). */
export interface RenameTarget {
  runId: string;
  previous: string | null;
}

/** The rename target of a task run. */
export function toRenameTarget(run: Pick<TaskRun, "run_id" | "name" | "renamed">): RenameTarget {
  return { runId: run.run_id, previous: run.renamed ? run.name : null };
}

/**
 * Give every target `name`, one at a time. On a refusal the runs already renamed get their
 * previous names back (best effort) and the refusal is thrown; when a roll back fails too
 * the error says how many runs kept the new name: `renamed 1 of 3: <reason>`.
 */
export async function renameEach(
  targets: readonly RenameTarget[],
  name: string | null,
  rename: (runId: string, name: string | null) => Promise<unknown>,
): Promise<void> {
  const generation=auth.snapshot().generation;
  const check=():void=>{if(!auth.current(generation)) throw new DOMException("Rename superseded","AbortError");};
  const done: RenameTarget[] = [];
  try {
    for (const t of targets) {
      check();
      await rename(t.runId, name);
      check();
      done.push(t);
    }
  } catch (err) {
    check();
    const reason = err instanceof Error ? err.message : String(err);
    let kept = 0;
    for (const t of done) {
      try {
        check();
        await rename(t.runId, t.previous);
      } catch {
        kept += 1;
      }
    }
    throw new Error(kept === 0 ? reason : `renamed ${kept} of ${targets.length}: ${reason}`);
  }
}

export interface RunNameProps {
  runId: string;
  /** Rename each of these runs instead of `runId` alone (a config: every run of the group). */
  runs?: readonly RenameTarget[];
  display: string;
  derived: string;
  renamed: boolean;
  /** What on the text starts editing: "click" (run header) or "dblclick" (list rows). The pencil always does. */
  editOn?: "click" | "dblclick";
  /** Accessible name of the pencil (default "Rename"); list rows add the name, `Rename <name>`. */
  label?: string;
  className?: string;
}

interface Shown {
  display: string;
  renamed: boolean;
}

export function RunName({
  runId,
  runs,
  display,
  derived,
  renamed,
  editOn = "click",
  label = "Rename",
  className,
}: RunNameProps): ReactElement {
  const me=useMe();
  const allowed=hasScope(me.data,"launch");
  const rename = useRenameRun();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(display);
  const [shown, setShown] = useState<Shown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;};},[]);
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
    if(!allowed) return;
    setText(current.display);
    setError(null);
    setEditing(true);
  };
  const cancel = () => {
    setEditing(false);
    setError(null);
  };
  const send = (name: string | null) => {
    if(!allowed) return;
    const credential=auth.capture();
    const before = current;
    setShown(name === null ? { display: derived, renamed: false } : { display: name, renamed: true });
    setEditing(false);
    setError(null);
    const targets = runs && runs.length > 0 ? runs : [{ runId, previous: before.renamed ? before.display : null }];
    void (async () => {
      try {
        await renameEach(targets, name, (id, to) => rename.mutateAsync({ runId: id, name: to, credential }));
      } catch (err) {
        if(!mounted.current || !auth.current(credential.generation)) return;
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
      <button type="button" className="pen" disabled={!allowed} aria-label={label} title="Rename" onClick={start}>
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
