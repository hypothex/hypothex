/** Run Files tab (spec 4.3): command, code, every recorded file, data, checkpoints. */
import { shellJoin } from "../pages/components/format";
import { CheckpointTable } from "../pages/components/TrainingDetails";
import { gitLine } from "../pages/components/WhereList";
import { FileList } from "./FileList";
import { allFiles, codeRows, dataRows, filesHost } from "./files";
import type { RunContext } from "./runContext";

export function FilesTab({ ctx }: { ctx: RunContext }) {
  const { record, detail } = ctx;
  const git = gitLine(record.git);
  const cmd = shellJoin(record.command);
  const tmpl = shellJoin(record.command_template);
  const training = (ctx.kind?.kind ?? ctx.taskRuns?.kind) === "training";
  return (
    <div className="rmain">
      <section aria-label="Command">
        <h3>Command</h3>
        <pre className="cmd mono">{cmd}</pre>
        {tmpl !== cmd ? (
          <p className="muted">
            template <code>{tmpl}</code>
          </p>
        ) : null}
        {git ? (
          <p className="gitline" title={git.untracked.length ? git.untracked.join("\n") : undefined}>
            <b className="mono">{git.ref}</b> <span className={git.state}>{git.text}</span>
          </p>
        ) : null}
      </section>
      <section aria-label="Code">
        <h3>Code</h3>
        <FileList rows={codeRows(detail)} />
      </section>
      <section aria-label="Run files">
        <h3>
          Files <span className="muted">{`on ${filesHost(detail)}`}</span>
        </h3>
        <FileList rows={allFiles(detail)} />
      </section>
      {record.datasets.length > 0 ? (
        <section aria-label="Data">
          <h3>Data</h3>
          <FileList rows={dataRows(record)} />
        </section>
      ) : null}
      {training ? (
        <section aria-label="Checkpoints">
          <h3>Checkpoints</h3>
          <CheckpointTable artifacts={record.artifacts} />
        </section>
      ) : null}
    </div>
  );
}
