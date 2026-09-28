/** A run log tail (opened from failures and the Where list via `?log=<stream>`). */
import { useRunLogs } from "../../api/queries";
import { Figure } from "./Figure";
import { fmtBytes } from "./format";
import { AppLink, hrefs } from "./links";
import { ErrorBox, Loading } from "./QueryState";
import type { LogStream } from "./types";

export function LogView({ runId, stream, letter }: { runId: string; stream: LogStream; letter: string }) {
  const log = useRunLogs(runId, stream);
  return (
    <Figure letter={letter} title={stream} aside={log.data ? fmtBytes(log.data.size) : undefined}>
      {log.error ? (
        <ErrorBox error={log.error} />
      ) : log.data ? (
        <pre className="log">{log.data.text.trimEnd() || "empty"}</pre>
      ) : (
        <Loading />
      )}
      <AppLink className="btn link" href={hrefs.run(runId)}>
        close
      </AppLink>
    </Figure>
  );
}
