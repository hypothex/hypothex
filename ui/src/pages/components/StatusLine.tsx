/** The line under a run's title: status, time, seed, launcher, host, tags. */
import { fmtDuration, fmtTime, isAgent, runSeconds, shortId } from "./format";
import { AppLink, hrefs } from "./links";
import type { RunRecord } from "./types";

export function StatusLine({ record }: { record: RunRecord }) {
  const seconds = runSeconds(record);
  return (
    <p className="status">
      <span className={`st ${record.status}`}>
        <i />
        {record.status}
      </span>
      {seconds !== null ? <span>{fmtDuration(seconds)}</span> : null}
      {record.seed !== null ? <span>{`seed ${record.seed}`}</span> : null}
      <span title={record.created_at}>{fmtTime(record.created_at)}</span>
      <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
        <i />
        {record.created_by}
      </span>
      <span>{record.host}</span>
      {record.kind === "infer" ? (
        <span className="tag" title="inference-only run">
          infer
        </span>
      ) : null}
      {record.parent ? (
        <AppLink href={hrefs.run(record.parent)}>{`parent ${shortId(record.parent)}`}</AppLink>
      ) : null}
      {record.tags.map((tag) => (
        <span key={tag} className="tag">
          {tag}
        </span>
      ))}
    </p>
  );
}
