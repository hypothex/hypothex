/** Inline task selection using stored run detail, with a route out to the complete run. */
import { useEffect, useRef } from "react";
import { useRun, useTaskKind } from "../../api/queries";
import { Panel } from "../../chrome/Panel";
import { hrefs } from "./links";
import { ErrorBox } from "./QueryState";
import { ScoresList } from "./ScoresList";
import { StatusLine } from "./StatusLine";
import { CheckpointTable } from "./TrainingDetails";
import { WhereList } from "./WhereList";

export interface SelectedRunProps {
  runId: string;
  onClose: () => void;
}

/** Selected run pane. Its close action remains available while data loads or fails. */
export function SelectedRun({ runId, onClose }: SelectedRunProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    const pane = headingRef.current?.closest("[data-panel]");
    // Selection can originate many panels above this detail; reveal its heading.
    headingRef.current?.focus();
    return () => {
      const active = document.activeElement;
      if ((active === document.body || pane?.contains(active)) && previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [runId]);
  const run = useRun(runId);
  const record = run.data?.record;
  const kind = useTaskKind(record?.project ?? "", record?.task ?? "", { enabled: Boolean(record?.task) });
  return <Panel
    title={`Selected run · ${runId}`}
    label="Selected run"
    headingRef={headingRef}
    aside={<span style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <a href={hrefs.run(runId)} target="_blank" rel="noopener noreferrer" title="Open the full run in a new tab">Open run ↗</a>
      <button type="button" className="btn" aria-label="Close selected run" onClick={onClose}>Close</button>
    </span>}
  >
    {run.isPending ? <p role="status" className="small">Loading selected run…</p> : run.isError ? <ErrorBox error={run.error} /> : run.data && record ? <>
      <p>{record.hypothesis || "No hypothesis recorded."}</p>
      <StatusLine record={record} />
      {kind.data ? <p className="small">{kind.data.kind}</p> : null}
      {kind.isError ? <ErrorBox error={kind.error} /> : null}
      <h4>Parameters</h4>
      {Object.keys(record.params).length ? <dl>{Object.entries(record.params).map(([name, value]) => <div key={name} style={{ display: "flex", gap: 12 }}><dt>{name}</dt><dd style={{ margin: 0, overflowWrap: "anywhere" }}>{value}</dd></div>)}</dl> : <p className="small">No parameters recorded.</p>}
      <h4>Where</h4>
      <WhereList detail={run.data} />
      <h4>Evaluated scores</h4>
      <ScoresList scores={run.data.scores} metricNames={run.data.metric_names} primary={null} />
      {kind.data?.kind === "training" ? <>
        <h4>Checkpoint metrics</h4>
        <CheckpointTable artifacts={record.artifacts} />
      </> : null}
    </> : null}
  </Panel>;
}
