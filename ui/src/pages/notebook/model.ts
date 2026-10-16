import { ApiError } from "../../api/client";
import type { NotebookDay } from "../../api/models";
export interface Entry { at: string | null; author: string | null; text: string; week: string | null }
export function entries(text: string): Entry[] {
  const stamps: { index: number; end: number; at: string; author: string }[] = [];
  let offset = 0; let fenced = false;
  for (const line of text.split(/(?<=\n)/)) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    else if (!fenced) { const stamp = /^## (\d{4}-\d{2}-\d{2}T[^\n]+?) — ([^\r\n]+)\r?\n?$/.exec(line); if (stamp) stamps.push({ index: offset, end: offset + line.length, at: stamp[1], author: stamp[2] }); }
    offset += line.length;
  }
  const out: Entry[] = []; let start = 0; let at: string | null = null; let author: string | null = null;
  const push = (body: string): void => { if (body || at) out.push({ at, author, text: body, week: /^\s*\*\*(\d{4}-W\d{2})\*\*/.exec(body)?.[1] ?? null }); };
  for (const stamp of stamps) { push(text.slice(start, stamp.index)); at = stamp.at; author = stamp.author; start = stamp.end; }
  push(text.slice(start)); return out;
}
export function entryTime(at: string): string { return Number.isFinite(Date.parse(at)) ? at.slice(11, 16) : "—"; }
export const authorLabel = (author: string): string => author.startsWith("human:") ? `@${author.slice(6)}` : author;
export function runSegments(text: string): { text: string; runId?: string }[] {
  const out: { text: string; runId?: string }[] = []; let cursor = 0;
  for (const match of text.matchAll(/\[\[run:([A-Za-z0-9][A-Za-z0-9_.-]{0,79})\]\]/g)) { if (match.index! > cursor) out.push({ text: text.slice(cursor, match.index) }); out.push({ text: match[0], runId: match[1] }); cursor = match.index! + match[0].length; }
  if (cursor < text.length) out.push({ text: text.slice(cursor) }); return out;
}
export interface DiffLine { theirs: string | null; mine: string | null; kind: "same" | "changed" | "inserted" | "deleted" }
/** LCS for normal edits with deterministic linear fallback above four million cells. */
export function lineDiff(theirs: string, mine: string): DiffLine[] {
  const a = theirs.split("\n"); const b = mine.split("\n");
  if (a.length * b.length > 4_000_000) return Array.from({ length: Math.max(a.length, b.length) }, (_, i) => ({ theirs: a[i] ?? null, mine: b[i] ?? null, kind: a[i] === b[i] ? "same" : a[i] === undefined ? "inserted" : b[i] === undefined ? "deleted" : "changed" }));
  const width = b.length + 1; const matrix = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) matrix[i * width + j] = a[i] === b[j] ? 1 + matrix[(i + 1) * width + j + 1] : Math.max(matrix[(i + 1) * width + j], matrix[i * width + j + 1]);
  const out: DiffLine[] = []; let i = 0; let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) { out.push({ theirs: a[i++], mine: b[j++], kind: "same" }); }
    else if (i < a.length && (j === b.length || matrix[(i + 1) * width + j] >= matrix[i * width + j + 1])) out.push({ theirs: a[i++], mine: null, kind: "deleted" });
    else out.push({ theirs: null, mine: b[j++], kind: "inserted" });
  }
  return out;
}
export function conflictOf(error: unknown, project: string, day: string): NotebookDay | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.body || typeof error.body !== "object") return null;
  const body = error.body as Record<string, unknown>;
  if (body.type !== "NotebookConflictError") return null;
  const value = body.current;
  if (!value || typeof value !== "object") return null;
  const c = value as Record<string, unknown>;
  if (c.project !== project || c.day !== day || typeof c.text !== "string" || typeof c.hash !== "string" || !Array.isArray(c.runs) || !(c.updated_at === null || typeof c.updated_at === "string")) return null;
  if (c.runs.some((r: unknown) => {
    if (!r || typeof r !== "object") return true;
    const chip = r as Record<string, unknown>;
    return typeof chip.run_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(chip.run_id) || typeof chip.label !== "string" || !(chip.status === null || ["queued", "running", "finished", "failed", "killed", "lost"].includes(String(chip.status))) || !(chip.task === null || typeof chip.task === "string") || !(chip.primary === null || typeof chip.primary === "number" && Number.isFinite(chip.primary));
  })) return null;
  return c as unknown as NotebookDay;
}
export function withToday<T extends {day: string}>(days: T[], today: T): T[] { return [days.find((d) => d.day === today.day) ?? today, ...days.filter((d) => d.day !== today.day)]; }
export const utf8Bytes = (text: string): number => new TextEncoder().encode(text).length;
