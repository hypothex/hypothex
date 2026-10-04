/** Run panel: notes (`notes.md`), newest first shown, with Add note. */
import { useCallback, useRef, useState } from "react";
import { api } from "../../api/client";
import { queryKeys } from "../../api/queries";
import { fmtDate, isAgent } from "./format";
import { ErrorBox } from "./QueryState";
import { useAction } from "./useAction";

export interface NoteEntry {
  at: string;
  author: string;
  text: string;
}

const HEADER = /^## (\S+) — (.+)$/gm;

/** Split `notes.md` into entries (header format from `hypothex.core.fsutil`). */
export function parseNotes(raw: string): NoteEntry[] {
  const heads = [...raw.matchAll(HEADER)];
  if (heads.length === 0) {
    const text = raw.trim();
    return text ? [{ at: "", author: "", text }] : [];
  }
  return heads.map((m, i) => {
    const start = (m.index ?? 0) + m[0].length;
    const end = heads[i + 1]?.index ?? raw.length;
    return { at: m[1] ?? "", author: (m[2] ?? "").trim(), text: raw.slice(start, end).trim() };
  });
}

/**
 * Callback ref for the clamped note: true while CSS clips its text. Measured on attach,
 * on resize, and when `text` changes, so More shows exactly when text is hidden.
 */
function useClipped(text: string): [(el: HTMLElement | null) => void, boolean] {
  const [clipped, setClipped] = useState(false);
  const observer = useRef<ResizeObserver | null>(null);
  // `text` is a dep on purpose: a new callback re-attaches and re-measures.
  const ref = useCallback(
    (el: HTMLElement | null) => {
      observer.current?.disconnect();
      observer.current = null;
      if (!el) return;
      const read = (): void => setClipped(el.scrollHeight > el.clientHeight + 1);
      read();
      if (typeof ResizeObserver === "undefined") return;
      observer.current = new ResizeObserver(read);
      observer.current.observe(el);
    },
    [text],
  );
  return [ref, clipped];
}

export function Notes({ runId, notes }: { runId: string; notes: string }) {
  const entries = parseNotes(notes);
  const [all, setAll] = useState(false);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const add = useAction<unknown, string>({
    send: (note, opts) => api.note(runId, note, opts),
    invalidate: [queryKeys.run(runId)],
    onSuccess: () => {
      setText("");
      setEditing(false);
    },
  });
  const shown = all ? entries : entries.slice(-1);
  const [clipRef, clipped] = useClipped(entries.at(-1)?.text ?? "");
  const canExpand = entries.length > 1 || all || clipped;
  return (
    <div>
      {entries.length === 0 && !editing ? <p className="small">none</p> : null}
      {shown.map((entry, i) => (
        <div key={`${entry.at}-${i}`} className="notes">
          {entry.author || entry.at ? (
            <div className="by">
              {entry.author ? (
                <span className={`who ${isAgent(entry.author) ? "agent" : "human"}`}>
                  <i />
                  {entry.author}
                </span>
              ) : null}
              {entry.at ? <span>{fmtDate(entry.at)}</span> : null}
            </div>
          ) : null}
          {all ? <p>{entry.text}</p> : <p className="clip" ref={clipRef}>{entry.text}</p>}
        </div>
      ))}
      {editing ? (
        <div className="note-edit">
          <textarea aria-label="Note" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button
              type="button"
              className="btn primary"
              disabled={add.pending || text.trim() === ""}
              onClick={() => add.run(text.trim())}
            >
              Save
            </button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="row">
          {canExpand ? (
            <button type="button" className="btn" onClick={() => setAll(!all)}>
              {all ? "Less" : "More"}
            </button>
          ) : null}
          <button type="button" className="btn" onClick={() => setEditing(true)}>
            Add note
          </button>
        </div>
      )}
      {add.error ? <ErrorBox error={add.error} /> : null}
    </div>
  );
}
