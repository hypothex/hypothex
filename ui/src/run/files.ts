import { cleanedArtifact } from "../pages/components/cleaned";
/** The run's files as list rows (spec 4.3 Files): name, path relative to the run folder, size, copy text. */
import type { CleanedArtifact, RunDetail, RunRecord } from "../api/models";
import { displayPath, relativeTo, splitHostPath } from "../pages/components/format";
import { hrefs } from "../pages/components/links";

export type FileIcon = "folder" | "doc" | "box";

export interface FileRow {
  rawPath?:string;
  environmentId?:string|null;
  cleaned?:CleanedArtifact;
  icon: FileIcon;
  name: string;
  /** Relative to the run folder when inside it, else `host:path`. */
  path: string;
  /** The full `host:path` the Copy button copies. */
  copy: string;
  size: number | null;
  /** In-app link (the log rows open the Logs tab). */
  href?: string;
  note?: string;
}

interface Loc {
  host: string;
  path: string;
}

const STREAMS = ["stdout", "stderr", "supervisor"] as const;
const baseName = (p: string): string => p.replace(/\/+$/, "").split("/").pop() || p;
const iconOf = (p: string): FileIcon => (/\.[A-Za-z0-9]+$/.test(baseName(p)) ? "doc" : "folder");

function rowFor(loc: Loc, dir: Loc, extra: Partial<FileRow> = {}): FileRow {
  const rel = dir.host === loc.host ? relativeTo(loc.path, dir.path) : null;
  const full = displayPath(loc.host, loc.path);
  return { icon: iconOf(loc.path), name: baseName(loc.path), path: rel ?? full, copy: full, size: null, ...extra };
}

/** The machine the run folder is on: its `host:` prefix, else the run's own hostname. */
export function filesHost(detail: RunDetail): string {
  const dir = detail.paths.run_dir;
  const host = dir ? splitHostPath(dir).host : "local";
  return host === "local" ? detail.record.host : host;
}

function fileRows(detail: RunDetail, all: boolean): FileRow[] {
  const { paths, record } = detail;
  if (!paths.run_dir) return [];
  const dir = splitHostPath(paths.run_dir);
  const folder = displayPath(dir.host, dir.path);
  const rows: FileRow[] = [{ icon: "folder", name: "Run folder", path: folder, copy: folder, size: null }];
  for (const stream of STREAMS) {
    const p = paths[stream];
    if (p) rows.push(rowFor(splitHostPath(p), dir, { icon: "doc", href: hrefs.run(record.run_id, { tab: "logs", log: stream }) }));
  }
  for (const key of all ? ["predictions", "env", "config"] : ["predictions"]) {
    const p = paths[key];
    if (p) rows.push(rowFor(splitHostPath(p), dir));
  }
  if (all && (paths.diff || detail.has_diff)) {
    const diff = paths.diff ? splitHostPath(paths.diff) : { host: dir.host, path: `${dir.path}/git.diff` };
    rows.push(rowFor(diff, dir, { icon: "doc", note: "tracked diff" }));
  }
  for (const art of record.artifacts) {
    if (!all && art.kind !== "checkpoint") continue;
    const note = [art.kind, art.step !== null ? `step ${art.step}` : null].filter(Boolean).join(" · ");
    rows.push(rowFor({ host: art.host, path: art.path }, dir, { icon: art.kind === "checkpoint" ? "box" : iconOf(art.path), size: art.size, note,rawPath:art.path,environmentId:record.environment_id,cleaned:cleanedArtifact(art.path,record.environment_id,detail.cleaned) }));
  }
  return rows;
}

/** Run folder, logs, predictions and checkpoints (Overview tab). */
export function overviewFiles(detail: RunDetail): FileRow[] {
  return fileRows(detail, false);
}

/** Every recorded path of the run (Files tab). */
export function allFiles(detail: RunDetail): FileRow[] {
  return fileRows(detail, true);
}

/** The project checkout and working directory (Files tab "Code"). */
export function codeRows(detail: RunDetail): FileRow[] {
  const repo = splitHostPath(detail.paths.repo ?? detail.paths.cwd ?? detail.record.cwd);
  const rows: FileRow[] = [{ icon: "folder", name: "Project", path: displayPath(repo.host, repo.path), copy: displayPath(repo.host, repo.path), size: null }];
  const cwd = splitHostPath(detail.paths.cwd ?? detail.record.cwd);
  if (cwd.path !== repo.path) rows.push(rowFor(cwd, repo, { icon: "folder", name: "cwd" }));
  return rows;
}

/** The run's datasets (Files tab "Data"). */
export function dataRows(record: RunRecord): FileRow[] {
  return record.datasets.map((ds) => ({
    icon: iconOf(ds.path),
    name: `${ds.name} ${ds.version}${ds.split ? ` ${ds.split}` : ""}`,
    path: displayPath(ds.host, ds.path),
    copy: displayPath(ds.host, ds.path),
    size: ds.size,
  }));
}
