/**
 * Run panel "where everything is" (spec 8.1): code, data, run folder, logs,
 * predictions, checkpoints as host:path. The run folder is shown once and its
 * children relative to it; copy buttons copy the full path.
 */
import { CopyButton } from "./CopyButton";
import { displayPath, fmtBytes, isNum, relativeTo, shellJoin, splitHostPath, tailPath } from "./format";
import { AppLink, hrefs } from "./links";
import type { GitInfo, RunDetail } from "./types";

export interface WhereRow {
  display: string;
  copy: string;
  indent: boolean;
  note?: string;
  href?: string;
  /** The full path, when `display` is shortened. */
  title?: string;
}

/** Longest artifact path shown whole; longer ones outside the run folder show their tail. */
export const LONG_PATH = 48;

export interface WhereGroup {
  title: string;
  host: string;
  rows: WhereRow[];
}

export interface GitLine {
  ref: string;
  state: "clean" | "dirty" | "untracked";
  text: string;
  untracked: string[];
}

interface Loc {
  host: string;
  path: string;
}

function whereRow(loc: Loc, base: Loc | null, extra: Partial<WhereRow> = {}): WhereRow {
  const rel = base && base.host === loc.host ? relativeTo(loc.path, base.path) : null;
  const full = displayPath(loc.host, loc.path);
  return { display: rel ?? full, copy: full, indent: rel !== null, ...extra };
}

function joinNote(parts: (string | null)[]): string {
  return parts.filter((p): p is string => p !== null && p !== "").join(", ");
}

/** The git fields `gitLine` reads; the untracked fields may be missing on runs recorded before phase 1b. */
export type GitState = Pick<GitInfo, "commit" | "branch" | "dirty"> &
  Partial<Pick<GitInfo, "untracked_count" | "untracked" | "diff_hash">>;

/** Branch, short commit, and working-copy state; tracked changes and untracked files apart. */
export function gitLine(git: GitState): GitLine | null {
  if (!git.commit) return null;
  const ref = `${git.branch ?? "detached"} @ ${git.commit.slice(0, 7)}`;
  const count = git.untracked_count ?? 0;
  const untracked = git.untracked ?? [];
  if (git.dirty) {
    const text = count > 0 ? `tracked changes, ${count} untracked` : "tracked changes";
    return { ref, state: "dirty", text: git.diff_hash ? `${text} · patch ${git.diff_hash}` : text, untracked };
  }
  if (count > 0) return { ref, state: "untracked", text: "untracked files only", untracked };
  return { ref, state: "clean", text: "tracked clean", untracked: [] };
}

export function buildWhere(detail: RunDetail): WhereGroup[] {
  const { record, paths } = detail;
  const repo = splitHostPath(paths.repo ?? paths.cwd ?? record.cwd);
  const project: WhereGroup = { title: "Project", host: repo.host, rows: [whereRow(repo, null)] };
  const cwd = splitHostPath(paths.cwd ?? record.cwd);
  if (cwd.path !== repo.path) project.rows.push(whereRow(cwd, repo, { note: "cwd" }));

  const data: WhereGroup = { title: "Data", host: "", rows: [] };
  for (const ds of record.datasets) {
    const note = joinNote([
      `${ds.name} ${ds.version}${ds.split ? ` ${ds.split}` : ""}`,
      ds.size !== null ? fmtBytes(ds.size) : null,
    ]);
    const row = whereRow({ host: ds.host, path: ds.path }, repo, { note });
    if (row.indent) {
      project.rows.push(row);
    } else {
      data.rows.push(row);
      data.host = data.host || ds.host;
    }
  }

  const groups = [project];
  if (data.rows.length > 0) groups.push(data);

  const runDir = paths.run_dir;
  if (runDir) {
    const dir = splitHostPath(runDir);
    const run: WhereGroup = { title: "Run", host: dir.host, rows: [whereRow(dir, null)] };
    for (const stream of ["stdout", "stderr"] as const) {
      const p = paths[stream];
      if (p) {
        run.rows.push(whereRow(splitHostPath(p), dir, { href: hrefs.run(record.run_id, { log: stream }) }));
      }
    }
    for (const key of ["predictions", "env", "config"]) {
      const p = paths[key];
      if (p) run.rows.push(whereRow(splitHostPath(p), dir));
    }
    if (paths.diff || detail.has_diff) {
      const diff = paths.diff ? splitHostPath(paths.diff) : { host: dir.host, path: `${dir.path}/git.diff` };
      run.rows.push(whereRow(diff, dir, { note: "tracked diff" }));
    }
    for (const art of record.artifacts) {
      const note = joinNote([
        art.kind,
        isNum(art.step) ? `step ${art.step}` : null,
        isNum(art.size) ? fmtBytes(art.size) : null,
      ]);
      const row = whereRow({ host: art.host, path: art.path }, dir, { note });
      if (!row.indent && row.display.length > LONG_PATH) {
        row.display = displayPath(art.host, tailPath(art.path, 2));
        row.title = row.copy;
      }
      run.rows.push(row);
    }
    groups.push(run);
  }
  return groups;
}

export function WhereList({ detail }: { detail: RunDetail }) {
  const { record } = detail;
  const git = gitLine(record.git);
  const cmd = shellJoin(record.command);
  const tmpl = shellJoin(record.command_template);
  return (
    <div className="tree">
      <div className="cmdrow">
        <span className="k">Command</span>
        <div>
          <code className="cmd">{cmd}</code>
          {tmpl !== cmd ? (
            <p className="tmpl">
              template <code>{tmpl}</code>
            </p>
          ) : null}
        </div>
      </div>
      {buildWhere(detail).map((group) => {
        const [root, ...kids] = group.rows;
        if (!root) return null;
        return (
          <div key={group.title}>
            <div className="root">
              <span className="k">{group.title}</span>
              <span className="p">{root.display}</span>
              <span className="what">{root.note ?? ""}</span>
              <CopyButton text={root.copy} label={root.display} />
            </div>
            {group.title === "Project" && git ? (
              <p className="gitline" title={git.untracked.length ? git.untracked.join("\n") : undefined}>
                <b>{git.ref}</b> <span className={git.state}>{git.text}</span>
              </p>
            ) : null}
            {kids.length > 0 ? (
              <ul className="kids">
                {kids.map((row, i) => (
                  <li key={`${row.copy}-${i}`}>
                    <span className="br">{row.indent ? (i === kids.length - 1 ? "└" : "├") : "·"}</span>
                    <span className="p" title={row.title}>
                      {row.href ? (
                        <AppLink href={row.href} title="Open">
                          {row.display}
                        </AppLink>
                      ) : (
                        row.display
                      )}
                    </span>
                    <span className="what">{row.note ?? ""}</span>
                    <CopyButton text={row.copy} label={row.display} />
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
