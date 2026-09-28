/** Examples page figures: outcome table, per-example strip, sign test, B's errors. */
import { max, range } from "d3-array";
import { scaleBand, scaleLinear } from "d3-scale";
import type { ReactElement } from "react";
import { useElementWidth } from "../../charts/Scale";
import { type Segment, binomPmf, exampleTotal, signTestP, stripSegments } from "./examples";
import { fmtP, fmtValue } from "./format";
import type { ExampleDiff, PredictionRow } from "./types";

export function OutcomeTable({ labelA, labelB, diff }: { labelA: string; labelB: string; diff: ExampleDiff }) {
  return (
    <table className="ot">
      <thead>
        <tr>
          <th />
          <th>{`${labelB} right`}</th>
          <th>{`${labelB} wrong`}</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th className="rh">{`${labelA} right`}</th>
          <td className="same">
            <span className="n">{diff.both_pass}</span>
          </td>
          <td className="bk">
            <span className="n">{diff.broken.length}</span>
            <span className="w">
              <i className="sw broken" />
              broken
            </span>
          </td>
        </tr>
        <tr>
          <th className="rh">{`${labelA} wrong`}</th>
          <td className="fx">
            <span className="n">{diff.fixed.length}</span>
            <span className="w">
              <i className="sw fixed" />
              fixed
            </span>
          </td>
          <td className="same">
            <span className="n">{diff.both_fail}</span>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

const STRIP_W = 1000;
const STRIP_H = 44;
const MAX_MARKS = 2000;

function marks(segments: Segment[], n: number): ReactElement[] {
  const out: ReactElement[] = [];
  if (n > MAX_MARKS) {
    let x = 0;
    for (const seg of segments) {
      if (seg.count === 0) continue;
      const w = (STRIP_W * seg.count) / n;
      out.push(
        <rect key={seg.outcome} className={seg.outcome} x={x} y={0} width={w} height={STRIP_H}>
          <title>{seg.label}</title>
        </rect>,
      );
      x += w;
    }
    return out;
  }
  const w = STRIP_W / n;
  const gap = w > 3 ? w * 0.25 : 0;
  let i = 0;
  for (const seg of segments) {
    for (let k = 0; k < seg.count; k++) {
      const id = seg.ids[k];
      out.push(
        <rect key={i} className={seg.outcome} x={i * w} y={0} width={w - gap} height={STRIP_H}>
          {id ? <title>{id}</title> : null}
        </rect>,
      );
      i += 1;
    }
  }
  return out;
}

export function ExampleStrip({ diff }: { diff: ExampleDiff }) {
  const n = exampleTotal(diff);
  if (n === 0) return <p className="small">no shared examples</p>;
  const segments = stripSegments(diff);
  return (
    <div className="strip">
      <svg viewBox={`0 0 ${STRIP_W} ${STRIP_H}`} preserveAspectRatio="none" aria-label="One mark per example">
        {marks(segments, n)}
      </svg>
      <ul className="strip-key">
        {segments.map((seg) => (
          <li key={seg.outcome}>
            <i className={`sw ${seg.outcome}`} />
            {seg.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Width used before layout is known (and in test DOMs). */
export const ST_FALLBACK_W = 640;
const ST_H = 220;
const ST_BOTTOM = 24;
const ST_TOP = 40;

export function SignTestChart({ fixed, broken }: { fixed: number; broken: number }) {
  const [ref, ST_W] = useElementWidth<HTMLDivElement>(ST_FALLBACK_W);
  const n = fixed + broken;
  if (n === 0) return <p className="small">no changed examples</p>;
  const pmf = binomPmf(n);
  const p = signTestP(fixed, broken);
  const lo = Math.min(fixed, broken);
  const hi = n - lo;
  const x = scaleBand<number>().domain(range(n + 1)).range([0, ST_W]).padding(0.25);
  const y = scaleLinear()
    .domain([0, max(pmf) ?? 1])
    .range([ST_H - ST_BOTTOM, ST_TOP]);
  const bw = x.bandwidth();
  // at least ~28 px per labelled tick, so the fixed-size labels never collide
  const every = Math.max(1, Math.ceil((n + 1) / Math.max(1, Math.floor(ST_W / 28))));
  const ox = (x(fixed) ?? 0) + bw / 2;
  return (
    <div ref={ref} className="signtest" title="Exact two-sided binomial test on the examples that changed">
      <svg width={ST_W} height={ST_H} aria-label="Sign test null distribution">
        {pmf.map((v, k) => (
          <rect
            key={`b${k}`}
            data-tail={k <= lo || k >= hi ? "true" : "false"}
            x={x(k) ?? 0}
            y={y(v)}
            width={bw}
            height={ST_H - ST_BOTTOM - y(v)}
          >
            <title>{`${k} fixed: ${(v * 100).toFixed(1)}%`}</title>
          </rect>
        ))}
        {pmf.map((_, k) =>
          k % every === 0 ? (
            <text key={`t${k}`} x={(x(k) ?? 0) + bw / 2} y={ST_H - 6} textAnchor="middle">
              {k}
            </text>
          ) : null,
        )}
        <line className="obs" x1={ox} x2={ox} y1={ST_TOP - 4} y2={y(pmf[fixed] ?? 0)} />
        <text className="obs-l" x={ox} y={ST_TOP - 24} textAnchor="middle">
          {`${fixed}:${broken}`}
        </text>
        <text className="obs-l" x={ox} y={ST_TOP - 10} textAnchor="middle">
          {fmtP(p)}
        </text>
      </svg>
    </div>
  );
}

export interface ErrorsTableProps {
  rows: PredictionRow[];
  total: number;
  labelA: string;
  labelB: string;
  brokenIds: ReadonlySet<string>;
  onMore: () => void;
}

/** B's failing examples with B's answer, the label, and whether A got them right. */
export function ErrorsTable({ rows, total, labelA, labelB, brokenIds, onMore }: ErrorsTableProps) {
  if (total === 0) return <p className="small">none</p>;
  return (
    <div>
      <table className="tbl">
        <thead>
          <tr>
            <th>Example</th>
            <th className="r">{labelB}</th>
            <th className="r">label</th>
            <th>{labelA}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const aRight = brokenIds.has(row.id);
            return (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td className="r">{fmtValue(row.prediction)}</td>
                <td className="r">{fmtValue(row.reference)}</td>
                <td>
                  <i className={aRight ? "sw broken" : "sw both_fail"} />
                  {aRight ? "right" : "wrong"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {total > rows.length ? (
        <button type="button" className="btn link" onClick={onMore}>
          {`+${total - rows.length} more`}
        </button>
      ) : null}
    </div>
  );
}
