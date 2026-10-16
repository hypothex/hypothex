import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { auth } from "../../api/auth";
import type { ExportFormat, NoiseMode } from "../../api/models";
import { useExport } from "../../api/queries";
import { OpeningDialog } from "./OpeningDialog";
import "./export.css";
export function exportFilename(task: string, format: ExportFormat): string {
  const base = task.replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^\.+/, "").slice(0, 100) || "task";
  return `${base}.${{ latex: "tex", markdown: "md", csv: "csv" }[format]}`;
}
export function ExportMenu({ project, task, primary, ready }: { project: string; task: string; primary: string | null | undefined; ready: boolean }) {
  const [open, setOpen] = useState(false); const [format, setFormat] = useState<ExportFormat>("markdown"); const [noise, setNoise] = useState<NoiseMode>("both"); const [digits, setDigits] = useState("3"); const [message, setMessage] = useState("");
  const generation = useSyncExternalStore(auth.subscribe, auth.snapshot).generation;
  const validDigits = /^[0-6]$/.test(digits);
  const query = useExport(project, task, { primary: primary ?? undefined, format, noise, digits: validDigits ? Number(digits) : 3 }, { enabled: open && ready && !!primary && validDigits });
  const can = open && ready && !!primary && validDigits && !query.isPending && !query.isFetching && !query.isError && !query.isPlaceholderData && typeof query.data === "string";
  const identity = JSON.stringify([project, task, primary, generation, format, noise, digits]); const current = useRef({ identity, can }); current.current = { identity, can };
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setOpen(false); setMessage(""); }, [project, task, primary, generation]);
  useEffect(() => { setMessage(""); }, [identity, query.isFetching]);
  const copy = async (): Promise<void> => {
    if (!can || typeof query.data !== "string") return; const expected = identity;
    try { await navigator.clipboard.writeText(query.data); if (mounted.current && current.current.identity === expected && current.current.can && auth.current(generation)) setMessage("Copied"); }
    catch { if (mounted.current && current.current.identity === expected && current.current.can) setMessage("Clipboard unavailable; select the preview to copy."); }
  };
  const download = (): void => {
    if (!can || !auth.current(generation) || typeof query.data !== "string") return;
    const url = URL.createObjectURL(new Blob([query.data], { type: format === "csv" ? "text/csv;charset=utf-8" : "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = exportFilename(task, format); anchor.style.display = "none";
    try { document.body.append(anchor); anchor.click(); } finally { anchor.remove(); URL.revokeObjectURL(url); }
  };
  const lines = query.data?.split("\n") ?? [];
  return <><button className="btn" disabled={!ready || !primary} onClick={() => setOpen(true)}>Export</button>{open ? <OpeningDialog title="Export" onClose={() => setOpen(false)}><div className="export-options">
    <label>Format<select value={format} onChange={(e) => setFormat(e.target.value as ExportFormat)}><option value="latex">LaTeX</option><option value="markdown">Markdown</option><option value="csv">CSV</option></select></label>
    <label>Noise<select value={noise} onChange={(e) => setNoise(e.target.value as NoiseMode)}>{["both", "seed", "test", "none"].map((value) => <option key={value}>{value}</option>)}</select></label>
    <label>Digits<input type="number" min="0" max="6" step="1" value={digits} onChange={(e) => setDigits(e.target.value)} /></label>
  </div>{!validDigits ? <p role="alert">Digits must be an integer from 0 to 6.</p> : null}{query.isFetching ? <p role="status">Loading export…</p> : null}{query.error ? <p role="alert">{query.error.message}</p> : null}
    <section aria-label="Preview"><h3>Preview</h3><pre className="export-preview">{lines.slice(0, 6).join("\n")}</pre>{lines.length > 6 ? <p>{lines.length - 6} more lines</p> : null}</section>
    <button className="btn" disabled={!can} onClick={() => void copy()}>Copy</button><button className="btn" disabled={!can} onClick={download}>Download</button>{message ? <p role="status">{message}</p> : null}
  </OpeningDialog> : null}</>;
}
