/** Measured iteration outcomes and bounded system-benchmark source inspection. */
import { useState } from "react";
import type { ReactElement } from "react";
import type { ExampleDiff, Leaderboard, RunDetail } from "../../api/models";
import { useCompareExamples, useLeaderboard, useRun, useRunPredictions, useViewQuery } from "../../api/queries";
import { pickExampleField } from "../Examples";
import { ErrorBox, Loading } from "./QueryState";
import { exampleTotal, stripSegments } from "./examples";
import { primaryMetricName } from "./format";
import { AppLink, hrefs } from "./links";

/** Refuse ID-only comparisons across different or unknown dataset populations. */
export function comparisonProblem(a: RunDetail, b: RunDetail, metric: string): string | null {
  if (a.record.project !== b.record.project || a.record.task !== b.record.task) return "runs belong to different tasks";
  const datasets = (run: RunDetail): string[] => run.record.datasets.map(d => JSON.stringify([d.name, d.version, d.split, d.hash])).sort();
  if (!a.record.datasets.length || !b.record.datasets.length || [...a.record.datasets, ...b.record.datasets].some(d => !d.hash)) return "dataset fingerprint is unknown";
  if (JSON.stringify(datasets(a)) !== JSON.stringify(datasets(b))) return "dataset fingerprints or splits differ";
  const [name, version] = metric.split("@");
  if (!version) return "the selected metric version is unavailable for one run";
  // Evaluation writes every output key (including a wildcard error) with one timestamp.
  // Older successful records and their per-example file may survive a failed retry.
  // Inspect the latest attempt before considering success or source provenance.
  const attempts = [a, b].map(run => {
    const matching = run.scores.filter(score => score.metric === name && score.version === version);
    const latest = matching.reduce((time, score) => score.created_at > time ? score.created_at : time, "");
    return matching.filter(score => score.created_at === latest);
  });
  if (attempts.some(scores => !scores.length)) return "the selected metric version is unavailable for one run";
  if (attempts.some(scores => scores.some(score => score.error !== null))) return "latest evaluation failed for one run";
  if (attempts.some(scores => scores.some(score => score.value === null || !Number.isFinite(score.value)))) return "latest evaluation has no usable score";
  const hashes = attempts.map(scores => new Set(scores.map(score => score.source_hash || "unknown")));
  if (hashes.some(values => values.size !== 1 || values.has("unknown"))) return "metric source fingerprint is unknown or ambiguous";
  if (JSON.stringify([...hashes[0]!].sort()) !== JSON.stringify([...hashes[1]!].sort())) return "metric source fingerprints differ";
  if (attempts.some(scores => scores.some(score =>
    !score.per_example_hash?.trim() || !score.evaluation_ids_hash?.trim() ||
    !Number.isSafeInteger(score.evaluation_examples) || (score.evaluation_examples ?? 0) <= 0,
  ))) return "latest evaluation has no bound per-example population; re-evaluate these runs";
  if (attempts.some(scores => new Set(scores.map(score => JSON.stringify([
    score.per_example_hash, score.evaluation_ids_hash, score.evaluation_examples,
  ]))).size !== 1)) return "latest evaluation has conflicting per-example bindings";
  return null;
}

function OutcomeWaffle({ diff }: { diff: ExampleDiff }): ReactElement {
  const total = exampleTotal(diff);
  const segments = stripSegments(diff);
  return <>
    <p>{`${diff.fixed.length} fixed · ${diff.broken.length} broken · ${total} shared examples`}</p>
    {total > 0 ? <div role="img" aria-label={`Example outcomes: ${diff.fixed.length} fixed, ${diff.broken.length} broken, ${total} shared`}>
      <div style={{ display: "flex", gap: 2, flexWrap: total <= 400 ? "wrap" : "nowrap" }}>
        {segments.flatMap(seg => total <= 400
          ? Array.from({ length: seg.count }, (_, i) => <span key={`${seg.outcome}-${i}`} title={`${seg.outcome}${seg.ids[i] ? `: ${seg.ids[i]}` : ""}`} style={{ width: 9, height: 9, background: outcomeColor(seg.outcome) }} />)
          : seg.count > 0 ? [<span key={seg.outcome} title={`${seg.label}: ${seg.count}`} style={{ flex: seg.count, height: 20, background: outcomeColor(seg.outcome) }} />] : [])}
      </div>
      <p className="small" title={total <= 400 ? "One square per shared example." : "Segment widths show outcome proportions."}>{diff.both_pass} both pass · {diff.both_fail} both fail</p>
    </div> : <p>No shared scored examples.</p>}
  </>;
}
function outcomeColor(outcome: string): string {
  return ({ fixed: "var(--green, #3c8767)", broken: "var(--red, #bc5b54)", both_pass: "#a5bbb0", both_fail: "#d2cbc0" })[outcome] ?? "#aaa";
}
function FlipComparison({ a, b, metric }: { a: string; b: string; metric: string }): ReactElement {
  const runA = useRun(a);
  const runB = useRun(b);
  const problem = runA.data && runB.data ? comparisonProblem(runA.data, runB.data, metric) : null;
  const ready = !!runA.data && !!runB.data && !problem && a !== b;
  const probe = useRunPredictions(b, { metric, limit: 100 }, { enabled: ready });
  const field = probe.data?.rows.map(row => pickExampleField({ ...probe.data!, rows: [row] }, metric)).find(value => value !== undefined);
  const diff = useCompareExamples(a, b, metric, field, { enabled: ready && !!field, requireBound: true });
  if (a === b) return <p>Select two different groups.</p>;
  if (runA.isError || runB.isError) return <ErrorBox error={runA.error ?? runB.error} />;
  if (runA.isPending || runB.isPending) return <Loading />;
  if (problem) return <p role="status">Incompatible comparison: {problem}.</p>;
  if (probe.isError) return <ErrorBox error={probe.error} />;
  if (probe.isPending) return <Loading />;
  if (!field) return <p>No binary per-example outcome found in the first 100 predictions.</p>;
  if (diff.isError) return <ErrorBox error={diff.error} />;
  if (!diff.data) return <Loading />;
  return <><OutcomeWaffle diff={diff.data} /><AppLink href={hrefs.examples(a, b, metric)}>Inspect shared examples</AppLink><p className="small" title="Latest run of each selected group; outcomes include only example IDs scored by both runs.">Latest runs · shared examples only</p></>;
}

export function AgentIterationFlips({ project, task, board }: { project: string; task: string; board?: Leaderboard }): ReactElement {
  const query = useLeaderboard(project, task, [], { enabled: !board });
  const data = board ?? query.data;
  const [earlier, setEarlier] = useState<string | null>(null);
  const [later, setLater] = useState<string | null>(null);
  const rows = data?.rows ?? [];
  const a = rows.find(r => r.group_id === earlier) ?? rows[1];
  const b = rows.find(r => r.group_id === later) ?? rows[0];
  const name = data ? primaryMetricName(data.primary) : null;
  const version = name ? data?.metric_versions[name] : null;
  return <section aria-label="Iteration example changes">
    <h3>Example changes between versions</h3>
    {!board && query.isError ? <ErrorBox error={query.error} /> : !data ? <Loading /> : rows.length < 2 ? <p>Needs two scored groups.</p> : <>
      <div className="row">
        <label>Earlier version / group <select aria-label="Earlier version / group" value={a?.group_id ?? ""} onChange={e => setEarlier(e.target.value)}>{rows.map(r => <option key={r.group_id} value={r.group_id}>{r.label}</option>)}</select></label>
        <label>Later version / group <select aria-label="Later version / group" value={b?.group_id ?? ""} onChange={e => setLater(e.target.value)}>{rows.map(r => <option key={r.group_id} value={r.group_id}>{r.label}</option>)}</select></label>
      </div>
      {name && version && a && b ? <FlipComparison a={a.latest_run_id} b={b.latest_run_id} metric={`${name}@${version}`} /> : <p>Metric version unknown.</p>}
    </>}
  </section>;
}

export const RAW_SAMPLE_LIMIT = 100;
export function SystemRawSamples({ project, task, selectedRunId }: { project: string; task: string; selectedRunId?: string }): ReactElement {
  const query = useViewQuery(project, task, { panel: { type: "table", title: "Raw samples", data: { source: "samples", fields: ["name", "value"], ...(selectedRunId ? { filter: { run_id: selectedRunId } } : {}) } } });
  const panel = query.data?.panels[0];
  const rows = panel?.rows.slice(0, RAW_SAMPLE_LIMIT) ?? [];
  const total = typeof panel?.meta.total === "number" && Number.isFinite(panel.meta.total) ? panel.meta.total : null;
  const warnings = Array.isArray(panel?.meta.warnings) ? panel.meta.warnings.filter((v): v is string => typeof v === "string") : [];
  return <section aria-label="Raw benchmark samples"><h3>Raw samples</h3>
    <p className="small">{selectedRunId ? `Run ${selectedRunId}` : "All task runs"}</p>
    {query.isError ? <ErrorBox error={query.error} /> : query.isPending || query.isPlaceholderData ? <Loading /> : panel?.meta.error ? <ErrorBox error={panel.meta.error} /> : !panel ? <p role="alert">Raw sample result is unavailable.</p> : <>
      <p>{total === null ? `Showing ${rows.length} samples; total unknown.` : `Showing ${rows.length} of ${total} samples.`}</p>
      {warnings.map(w => <p className="small" key={w}>{w}</p>)}
      {rows.length ? <div style={{ overflowX: "auto" }}><table className="tbl" aria-label="Raw samples"><thead><tr><th>Run</th><th>Repeat</th><th>Series</th><th>Value</th></tr></thead><tbody>{rows.map((row, i) => <tr key={`${row.run_id}-${i}`}><td>{String(row.run_id ?? "unknown")}</td><td>{String(row.seed ?? "unknown")}</td><td>{String(row.name ?? "unknown")}</td><td>{String(row.value ?? "unknown")}</td></tr>)}</tbody></table></div> : <p>No raw samples returned.</p>}
    </>}
  </section>;
}

export interface RepeatObservation { run_id: string; value: number; fingerprint?: string | null }
export interface RepeatFlag { runId: string; relativeDelta: number }
export interface RepeatFlagResult { complete: boolean; flags: RepeatFlag[]; reason: string | null }
/** Apply the documented >10% p95-vs-median rule only to a complete comparable group. */
export function repeatFlags(rows: readonly RepeatObservation[], expectedRunIds: readonly string[]): RepeatFlagResult {
  const unknown = (reason: string): RepeatFlagResult => ({ complete: false, flags: [], reason });
  const expected = new Set(expectedRunIds);
  if (expected.size < 2) return unknown("At least two repeats are needed");
  const selected = rows.filter(r => expected.has(r.run_id));
  if (selected.length !== expected.size || new Set(selected.map(r => r.run_id)).size !== expected.size) return unknown("Repeat score coverage is incomplete or duplicated");
  if (selected.some(r => !Number.isFinite(r.value) || r.value < 0 || !r.fingerprint)) return unknown("Repeat score or fingerprint is unknown");
  if (new Set(selected.map(r => r.fingerprint)).size !== 1) return unknown("Repeat score fingerprints differ");
  const values = selected.map(r => r.value).sort((a, b) => a - b);
  const middle = Math.floor(values.length / 2);
  const median = values.length % 2 ? values[middle]! : (values[middle - 1]! + values[middle]!) / 2;
  if (median <= 0) return unknown("Median repeat latency is not positive");
  return { complete: true, flags: selected.filter(r => r.value > median * 1.1).map(r => ({ runId: r.run_id, relativeDelta: (r.value - median) / median })), reason: null };
}
