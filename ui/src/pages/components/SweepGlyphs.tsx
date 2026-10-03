/**
 * Run-state glyphs from the phase 2 mockup (filled dot = finished, ringed dot = running,
 * ring = queued, half-filled ring = stale, red cross = failed or lost, grey cross =
 * killed), a cell's run list, and the sweep progress strip.
 */
import type { ReactElement } from "react";
import type { RunStatus } from "../../api/models";
import { shortId } from "./format";
import { AppLink, hrefs } from "./links";
import { type RunGlyphState, type SweepCellRun, progressLabel, progressSegments } from "./SweepModel";

/** Runs listed in one cell before the rest collapse into `+n`. */
export const RUN_LIST_MAX = 6;

const CROSS = "M1.4 1.4L8.6 8.6M8.6 1.4L1.4 8.6";

/** The glyph of one run state, as a small inline SVG (decorative: the text says the state). */
export function RunGlyph({ state }: { state: RunGlyphState }): ReactElement {
  const box = (size: number, body: ReactElement): ReactElement => (
    <svg
      className="rg"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      data-glyph={state}
    >
      {body}
    </svg>
  );
  switch (state) {
    case "finished":
      return box(10, <circle className="fin" cx={5} cy={5} r={4} />);
    case "running":
      return box(
        12,
        <>
          <circle className="ring" cx={6} cy={6} r={5.2} />
          <circle className="dot" cx={6} cy={6} r={3} />
        </>,
      );
    case "queued":
      return box(10, <circle className="hollow" cx={5} cy={5} r={4} />);
    case "stale":
      return box(
        10,
        <>
          <circle className="stale-ring" cx={5} cy={5} r={4} />
          <path className="half" d="M5 1a4 4 0 0 1 0 8z" />
        </>,
      );
    case "killed":
      return box(10, <path className="x killed" d={CROSS} />);
    case "failed":
    case "lost":
      return box(10, <path className="x" d={CROSS} />);
  }
}

export interface SweepRunLinkProps {
  runId: string;
  state: RunGlyphState;
  title?: string;
}

/** Glyph plus short id, linking to the run page. */
export function SweepRunLink({ runId, state, title }: SweepRunLinkProps): ReactElement {
  return (
    <AppLink href={hrefs.run(runId)} title={title}>
      <RunGlyph state={state} />
      {shortId(runId)}
    </AppLink>
  );
}

export interface SweepRunListProps {
  runs: readonly SweepCellRun[];
  /** Shown state of a run, given the summary's status as fallback. */
  stateOf: (runId: string, fallback: RunStatus | null) => RunGlyphState;
}

/** A cell's runs: up to `RUN_LIST_MAX` links, then `+n`. */
export function SweepRunList({ runs, stateOf }: SweepRunListProps): ReactElement {
  const shown = runs.slice(0, RUN_LIST_MAX);
  const more = runs.length - shown.length;
  return (
    <span className="rl">
      {shown.map((r) => {
        const state = stateOf(r.run_id, r.status);
        const seed = r.seed !== null ? `, seed ${r.seed}` : "";
        return (
          <SweepRunLink
            key={r.run_id}
            runId={r.run_id}
            state={state}
            title={`${shortId(r.run_id)}${seed}, ${state}`}
          />
        );
      })}
      {more > 0 ? (
        <span className="more" title={`${more} more runs`}>
          {`+${more}`}
        </span>
      ) : null}
    </span>
  );
}

/** One segment per run of the sweep; the label reads the counts. */
export function SweepProgress({ counts }: { counts: Readonly<Record<string, number>> }): ReactElement {
  return (
    <div className="prog" role="img" aria-label={progressLabel(counts)}>
      {progressSegments(counts).map((kind, i) => (
        <i key={i} className={kind} />
      ))}
    </div>
  );
}
