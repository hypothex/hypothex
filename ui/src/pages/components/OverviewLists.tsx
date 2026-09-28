/** Overview side panels: running runs, failures, projects. */
import { CopyButton } from "./CopyButton";
import { firstClause, fmtClock, fmtScore, fmtTime, shortId, tailPath } from "./format";
import { AppLink, hrefs } from "./links";
import type { FailureRow, ProjectRow, RunRecord } from "./types";

export function RunningList({ runs }: { runs: RunRecord[] }) {
  if (runs.length === 0) return <p className="small">none</p>;
  return (
    <ul className="plain">
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

export function FailureList({ failures }: { failures: FailureRow[] }) {
  if (failures.length === 0) return <p className="small">none</p>;
  return (
    <div>
      {failures.map((f) => (
        <div key={f.run_id} className="fail-b">
          <span className="x">×</span>
          <b>{f.exit_code !== null ? `${f.label}, exit ${f.exit_code}` : f.label}</b>{" "}
          <span className="small">{`${fmtTime(f.created_at)}${f.retried_ok ? ", retry ok" : ""}`}</span>
          <div className="p" title={f.stderr_path}>
            {tailPath(f.stderr_path)}
          </div>
          <div className="row">
            <AppLink className="btn" href={hrefs.run(f.run_id, { log: "stderr" })}>
              Open stderr
            </AppLink>
            <CopyButton text={f.stderr_path} label="stderr path" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ProjectsTable({ projects }: { projects: ProjectRow[] }) {
  if (projects.length === 0) return <p className="small">none</p>;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Task</th>
          <th className="r">Runs</th>
          <th className="r">Best</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => (
          <tr key={`${p.project}/${p.task}`} title={p.kind}>
            <td>
              <AppLink href={hrefs.task(p.project, p.task)}>{`${p.project} / ${p.task}`}</AppLink>
            </td>
            <td className="r">{p.runs}</td>
            <td className="r">{fmtScore(p.best)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
