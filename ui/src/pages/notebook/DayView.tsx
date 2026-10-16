import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { auth } from "../../api/auth";
import type { NotebookDay } from "../../api/models";
import { notebookEditor, subscribeNotebookEditors } from "../../api/notebookEditors";
import { SafeMarkdown } from "../../panels/Markdown";
import { useIntent } from "../settings/intent";
import { RunChips } from "./RunChips";
import { authorLabel, conflictOf, entries, entryTime, lineDiff, utf8Bytes } from "./model";
interface Edit { project: string; day: string; text: string; base_hash: string; generation: number }
export function DayView({ day, writable }: { day: NotebookDay; writable: boolean }) {
  const [text, setText] = useState(""); const [edit, setEdit] = useState<Edit | null>(null); const [conflict, setConflict] = useState<NotebookDay | null>(null); const [copy, setCopy] = useState("");
  const client = useQueryClient(); const alive = useRef(true);
  const editor = useSyncExternalStore(subscribeNotebookEditors, () => notebookEditor(day.project, day.day));
  const invalidate = (): void => { void client.invalidateQueries({ queryKey: ["notebook", day.project] }); };
  const append = useIntent((body: { project: string; day: string; text: string }, opts) => api.appendNotebook(body.project, body.day, body.text, opts), (_, body) => { setText((current) => current === body.text ? "" : current); invalidate(); });
  const save = useIntent((body: Edit, opts) => api.replaceNotebook(body.project, body.day, body.text, body.base_hash, opts), () => { setEdit(null); setConflict(null); invalidate(); });
  useEffect(() => { if (save.error) setConflict(conflictOf(save.error, day.project, day.day)); }, [save.error, day.project, day.day]);
  useEffect(() => { setEdit(null); setConflict(null); setText(""); setCopy(""); }, [day.project, day.day, append.generation]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const submit = (draft: Edit): void => { if (!writable || !auth.current(draft.generation) || draft.project !== day.project || draft.day !== day.day || utf8Bytes(draft.text) > 1024 * 1024) return; setConflict(null); void save.run(draft); };
  const copyMine = async (): Promise<void> => {
    if (!edit || !auth.current(edit.generation)) return; const captured = edit;
    try { await navigator.clipboard.writeText(captured.text); if (alive.current && auth.current(captured.generation)) setCopy("Copied"); }
    catch { if (alive.current && auth.current(captured.generation)) setCopy("Clipboard unavailable"); }
  };
  const parsed = entries(day.text);
  return <section aria-label={`Notebook ${day.day}`} className="notebook-day">
    <header><h2>{day.day}</h2><p>{parsed.filter((e) => e.at).length} entries · {day.runs.length} run references</p><button className="btn" disabled={!writable || !!edit || append.pending} title={!writable ? "Requires launch scope" : undefined} onClick={() => setEdit({ project: day.project, day: day.day, text: day.text, base_hash: day.hash, generation: append.generation })}>Edit day</button></header>
    {!writable ? <p>Read-only: writing requires launch scope.</p> : null}
    {edit ? <div><label className="notebook-editor">Day text<textarea value={edit.text} readOnly={save.pending} onChange={(e) => setEdit({ ...edit, text: e.target.value })} /></label><p>{utf8Bytes(edit.text)} / 1048576 bytes</p><button className="btn" disabled={save.pending || !writable || utf8Bytes(edit.text) > 1048576} onClick={() => submit(edit)}>Save</button><button className="btn" disabled={save.pending} onClick={() => { setEdit(null); setConflict(null); save.reset(); }}>Cancel</button></div> : <div>{!day.text ? <p>No entries yet</p> : parsed.map((entry, i) => <article key={i} className={entry.week ? "notebook-week" : "notebook-entry"} aria-label={entry.week ? `Weekly summary ${entry.week}` : undefined}>{entry.at ? <header><time dateTime={entry.at} title={entry.at}>{entryTime(entry.at)}</time> · {authorLabel(entry.author ?? "")}</header> : null}<SafeMarkdown text={entry.text} inline={(value, key) => <RunChips key={key} text={value} runs={day.runs} />} /></article>)}</div>}
    {save.error && !conflict ? <p role="alert">{save.error.message}{"status" in save.error && save.error.status === 413 ? " · Day exceeds the 1 MiB limit; your draft is retained." : ""}</p> : null}
    {conflict && edit ? <section role="alert" aria-label="Notebook conflict"><h3>Notebook conflict</h3><p>{editor?.author ? `Last seen editor: ${authorLabel(editor.author)} · ${editor.at}` : conflict.updated_at}</p><div className="notebook-conflict"><section aria-label="Theirs"><h4>Theirs</h4><pre>{conflict.text}</pre></section><section aria-label="Mine"><h4>Mine</h4><pre>{edit.text}</pre></section></div><details><summary>Line differences</summary>{lineDiff(conflict.text, edit.text).filter((line) => line.kind !== "same").map((line, i) => <pre key={i}>{line.kind}: {line.theirs ?? ""} → {line.mine ?? ""}</pre>)}</details>
      <button className="btn" disabled={save.pending} onClick={() => { client.setQueryData(["notebook", day.project, "day", day.day], conflict); setEdit(null); setConflict(null); save.reset(); invalidate(); }}>Use theirs</button>
      <button className="btn" disabled={save.pending || !writable} onClick={() => { const next = { ...edit, base_hash: conflict.hash }; setEdit(next); submit(next); }}>Keep mine</button><button className="btn" onClick={() => void copyMine()}>Copy mine</button>{copy ? <p role="status">{copy}</p> : null}
    </section> : null}
    <form onSubmit={(e) => { e.preventDefault(); if (writable && text.trim() && utf8Bytes(text) <= 1048576 && !append.pending) void append.run({ project: day.project, day: day.day, text }); }}><label className="notebook-editor">New entry<textarea value={text} readOnly={append.pending} disabled={!writable || !!edit} onChange={(e) => setText(e.target.value)} /></label><button className="btn" disabled={!writable || !!edit || append.pending || !text.trim() || utf8Bytes(text) > 1048576}>Add entry</button>{append.error ? <p role="alert">{append.error.message}</p> : null}</form>
  </section>;
}
