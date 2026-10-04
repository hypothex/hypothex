/** Overview side panels: running runs, failures, projects. */
import { Fragment } from "react";
import { CopyButton } from "./CopyButton";
import { firstClause, fmtClock, fmtScoreUnit, fmtTime, shortId, tailPath } from "./format";
import { AppLink, hrefs } from "./links";
import type { FailureRow, ProjectRow, RunRecord } from "./types";

function RunRows({ runs, label }: { runs: RunRecord[]; label: string }) {
  return (
    <ul className="plain" aria-label={label}>
      {runs.map((run) => (
        <li key={run.run_id}>
          <AppLink href={hrefs.run(run.run_id)}>
            {firstClause(run.hypothesis, `run ${shortId(run.run_id)}`)}
          </AppLink>
          <div className="small">
            {`${run.created_by}, ${fmtClock(run.started_at ?? run.created_at)}${run.task ? `, ${run.task}` : ""}`}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Active runs: running ones first, then queued ones under `waiting N` (they hold no GPU yet). */
export function RunningList({ runs }: { runs: RunRecord[] }) {
  if (runs.length === 0) return <p className="small">none</p>;
  const running = runs.filter((r) => r.status !== "queued");
  const waiting = runs.filter((r) => r.status === "queued");
  return (
    <>
      {running.length > 0 ? <RunRows runs={running} label="running" /> : null}
      {waiting.length > 0 ? (
        <>
          <p className="small" title="Queued: waiting for a host or GPUs">{`waiting ${waiting.length}`}</p>
          <RunRows runs={waiting} label="waiting" />
        </>
      ) : null}
    </>
  );
}

/** Failures with the same label and exit code, in first-seen order (rows come newest first). */
export function groupFailures(failures: FailureRow[]): FailureRow[][] {
  const groups = new Map<string, FailureRow[]>();
  for (const f of failures) {
    const key = JSON.stringify([f.label, f.exit_code]);
    const group = groups.get(key);
    if (group) group.push(f);
    else groups.set(key, [f]);
  }
  return [...groups.values()];
}

/** A path that wraps only after a `/`, never inside a name. */
function SlashPath({ path, title, className }: { path: string; title: string; className: string }) {
  const parts = path.split("/");
  return (
    <div className={className} title={title} style={{ wordBreak: "normal", overflowWrap: "break-word" }}>
      {parts.map((part, i) => (
        // segments repeat ("…", "logs") and never reorder, so the index is the key
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 ? (
            <>
              /<wbr />
            </>
          ) : null}
        </Fragment>
      ))}
    </div>
  );
}

export function FailureList({ failures }: { failures: FailureRow[] }) {
  if (failures.length === 0) return <p className="small">none</p>;
  return (
    <div>
      {groupFailures(failures).map((rows) => {
        const f = rows[0] as FailureRow;
        const many = rows.length > 1;
        const retried = rows.filter((r) => r.retried_ok).length;
        const retry = retried === 0 ? "" : retried === rows.length ? ", retry ok" : `, retried ×${retried}`;
        return (
          <div
            key={f.run_id}
            className="fail-b"
            title={many ? rows.map((r) => `${r.run_id} ${fmtTime(r.created_at)}`).join("\n") : undefined}
          >
            <span className="x">{many ? `×${rows.length}` : "×"}</span>
            <b>{f.exit_code !== null ? `${f.label}, exit ${f.exit_code}` : f.label}</b>{" "}
            <span className="small">{`${fmtTime(f.created_at)}${retry}`}</span>
            <SlashPath className="p" path={tailPath(f.stderr_path)} title={f.stderr_path} />
            <div className="row">
              <AppLink className="btn" href={hrefs.run(f.run_id, { log: "stderr" })}>
                Open stderr
              </AppLink>
              <CopyButton text={f.stderr_path} label="stderr path" />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ProjectsTable({ projects }: { projects: ProjectRow[] }) {
  if (projects.length === 0) return <p className="small">none</p>;
  return (
    <table className="tbl projects">
      <colgroup>
        <col />
        <col className="c-runs" />
        <col className="c-best" />
      </colgroup>
      <thead>
        <tr>
          <th>Task</th>
          <th className="r">Runs</th>
          <th className="r">Best</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => {
          const name = `${p.project} / ${p.task}`;
          return (
            <tr key={`${p.project}/${p.task}`} title={p.kind}>
              <td className="nm">
                <AppLink href={hrefs.task(p.project, p.task)} title={name}>
                  {name}
                </AppLink>
              </td>
              <td className="r">{p.runs}</td>
              <td className="r">{fmtScoreUnit(p.best, p.unit)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
