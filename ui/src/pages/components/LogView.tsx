/** A run log tail (the run page's Logs tab; failures link here with `?tab=logs&log=stderr`). */
import { useRunLogs } from "../../api/queries";
import type { LogStream } from "../../run/runContext";
import { fmtBytes } from "./format";
import { ErrorBox, Loading } from "./QueryState";

export function LogView({ runId, stream }: { runId: string; stream: LogStream }) {
  const log = useRunLogs(runId, stream);
  return (
    <section aria-label={stream} className="logview">
      <h3>
        {stream}
        {log.data ? <span className="muted">{fmtBytes(log.data.size)}</span> : null}
      </h3>
      {log.error ? <ErrorBox error={log.error} /> : log.data ? <pre className="log">{log.data.text.trimEnd() || "empty"}</pre> : <Loading />}
    </section>
  );
}
