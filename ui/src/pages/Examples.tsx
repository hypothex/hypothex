/**
 * Examples screen (spec 8.3.4, restyled in v5 4.2): two runs compared example by example:
 * 2×2 outcome table, sign-test p, one mark per example, and B's failing examples. The
 * heading names the pair; the counts and p-value are plain facts under it.
 */
import { useState } from "react";
import { useCompareExamples, useRun, useRunPredictions, useTask } from "../api/queries";
import { ErrorsTable, ExampleStrip, OutcomeTable, SignTestChart } from "./components/ExampleCharts";
import { examplesMeta, exampleTotal, pairLabels, signTestP } from "./components/examples";
import { Panel } from "../chrome/Panel";
import { fmtP, fmtScore, isAgent, primaryMetricName } from "./components/format";
import { AppLink, hrefs } from "./components/links";
import { ErrorBox, Loading } from "./components/QueryState";
import { scoreFor } from "./components/ScoresList";
import type { PredictionPage, RunDetail } from "./components/types";
import "./examples.css";

export interface ExamplesPageProps {
  a: string;
  b: string;
  metric?: string;
}

const FIRST_PAGE = 8;
const MORE = 50;

/** 0/1 or a bool, as the server's `pick_field` treats `correct` and `solved`. */
function isBinary(v: unknown): boolean {
  return typeof v === "boolean" || v === 0 || v === 1;
}

/**
 * The per-example field that marks success for `metric` (`name` or `name@version`), read from
 * the first row of a predictions page: `correct`, then `solved` (bool or 0/1), then the first
 * boolean field by name, the order of the server's `pick_field`. Phase 1a `compare/examples`
 * and `predictions` default to `correct` and drop examples without it, so an agent task
 * (`solved`) must send its field. `undefined` when the row has no scores for `metric`.
 */
export function pickExampleField(page: PredictionPage, metric: string): string | undefined {
  const scores = page.rows[0]?.scores ?? {};
  const fields =
    scores[metric] ?? Object.entries(scores).find(([ref]) => ref.split("@")[0] === metric)?.[1];
  if (!fields) return undefined;
  for (const name of ["correct", "solved"]) if (isBinary(fields[name])) return name;
  return Object.keys(fields)
    .sort()
    .find((name) => typeof fields[name] === "boolean");
}

interface SideProps {
  tag: "A" | "B";
  detail: RunDetail;
  label: string;
  metric: string | null;
}

function Side({ tag, detail, label, metric }: SideProps) {
  const record = detail.record;
  const value = metric ? scoreFor(detail.scores, metric) : null;
  return (
    <div>
      <div className="lbl">{tag}</div>
      <div className="row">
        <div>
          <div className="nm">{record.seed !== null ? `${label}, seed ${record.seed}` : label}</div>
          <div className="meta">
            <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
              <i />
              {record.created_by}
            </span>
            <AppLink href={hrefs.run(record.run_id)}>{record.run_id}</AppLink>
            <span title={record.git.commit ?? "No recorded commit"}>{record.git.commit?.slice(0, 7) ?? "no commit"}{record.git.dirty ? ` · dirty${record.git.diff_hash ? ` · patch ${record.git.diff_hash}` : ""}` : " · clean"}</span>
            {detail.paths.diff ? <code title="Recorded patch path">{detail.paths.diff}</code> : null}
          </div>
        </div>
        {value !== null && metric ? (
          <div className="acc">
            <span>{fmtScore(value)}</span>
            <small>{metric.replace("@", " ")}</small>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ExamplesPage({ a, b, metric }: ExamplesPageProps) {
  const runA = useRun(a);
  const runB = useRun(b);
  const recA = runA.data?.record;
  const recB = runB.data?.record;
  const project = recA?.project ?? "";
  const task = recA?.task ?? "";
  const explicit = metric ? String(metric) : null;

  const taskQ = useTask(project, task, { enabled: explicit === null && task !== "" });
  const metricRef = explicit ?? (taskQ.data ? primaryMetricName(taskQ.data.summary.primary) : null);
  // One row of B's per-example scores names the binary field (`correct`, `solved`, ...).
  // If this read fails, compare still runs without a field and shows the server's own error.
  const probe = { metric: metricRef ?? "", limit: 1 };
  const fieldQ = useRunPredictions(b, probe, { enabled: metricRef !== null });
  const field = fieldQ.data && metricRef ? pickExampleField(fieldQ.data, metricRef) : undefined;
  const diffQ = useCompareExamples(a, b, metricRef ?? "", field, {
    enabled: metricRef !== null && !fieldQ.isPending,
  });
  const diff = diffQ.data;
  const [limit, setLimit] = useState(FIRST_PAGE);
  const failing = { metric: diff?.metric, failures_only: true, field: diff?.field, limit };
  const errors = useRunPredictions(b, failing, { enabled: diff !== undefined, keepPrevious: true });

  const labels = recA && recB ? pairLabels(recA, recB) : null;
  const [labelA, labelB] = labels ?? ["A", "B"];
  const noMetric = explicit === null && recA !== undefined && task === "";
  const error = runA.error ?? runB.error ?? taskQ.error ?? diffQ.error;
  const changed = diff ? diff.fixed.length + diff.broken.length : 0;

  return (
    <div className="examples-page">
      <header className="ph">
        <h1>{labels ? `${labelB} vs ${labelA}` : "Examples"}</h1>
        <div className="facts">
          {task ? <AppLink href={hrefs.task(project, task)}>{`${project} / ${task}`}</AppLink> : null}
          {diff
            ? [`fixes ${diff.fixed.length}`, `breaks ${diff.broken.length}`, fmtP(signTestP(diff.fixed.length, diff.broken.length)), ...examplesMeta(diff)].map((text) => (
                <span key={text}>{text}</span>
              ))
            : null}
        </div>
      </header>
      {runA.data && runB.data ? (
        <div className="ab">
          <Side tag="A" detail={runA.data} label={labelA} metric={diff?.metric ?? null} />
          <Side tag="B" detail={runB.data} label={labelB} metric={diff?.metric ?? null} />
        </div>
      ) : null}
      {error ? <ErrorBox error={error} /> : null}
      {noMetric ? <ErrorBox error={new Error("no task: add ?metric=<name> to the URL")} /> : null}
      {diff ? (
        <>
          <div className="two-x">
            <Panel title="Outcomes">
              <OutcomeTable labelA={labelA} labelB={labelB} diff={diff} />
            </Panel>
            <Panel title="Sign test" aside={`${changed} changed`}>
              <SignTestChart fixed={diff.fixed.length} broken={diff.broken.length} />
            </Panel>
          </div>
          <Panel title="Per example" aside={String(exampleTotal(diff))}>
            <ExampleStrip diff={diff} />
          </Panel>
          <Panel
            title={`${labelB} errors`}
            aside={errors.data ? `${errors.data.rows.length} of ${errors.data.total}` : undefined}
          >
            {errors.error ? (
              <ErrorBox error={errors.error} />
            ) : errors.data ? (
              <ErrorsTable
                rows={errors.data.rows}
                total={errors.data.total}
                labelA={labelA}
                labelB={labelB}
                brokenIds={new Set(diff.broken)}
                onMore={() => setLimit(limit + MORE)}
              />
            ) : (
              <Loading />
            )}
          </Panel>
        </>
      ) : !error && !noMetric ? (
        <Loading />
      ) : null}
    </div>
  );
}
