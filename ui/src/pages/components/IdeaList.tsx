/** Overview panel: recent ideas, one row per seed group with seed marks and intervals. */
import { scaleLinear } from "d3-scale";
import { DASH, fmtClock, fmtInterval, fmtScore, isAgent, isNum } from "./format";
import { AppLink, hrefs } from "./links";
import { ACTIVE_STATUSES, FAILED_STATUSES, type IdeaRow, type RunStatus } from "./types";

const STRIP_W = 420;
const STRIP_H = 30;

/** The shared x domain of every row's interval, best band, and mean, padded 5%. */
export function ideaDomain(ideas: IdeaRow[]): [number, number] | null {
  const values: number[] = [];
  for (const idea of ideas) {
    const candidates = [
      idea.test_interval?.lo,
      idea.test_interval?.hi,
      idea.best_band?.lo,
      idea.best_band?.hi,
      idea.primary?.mean,
    ];
    for (const v of candidates) if (isNum(v)) values.push(v);
  }
  if (values.length === 0) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.05 || 0.01;
  return [lo - pad, hi + pad];
}

/** The big number of a row, or what happened instead. */
export function ideaScore(idea: IdeaRow): string {
  if (idea.primary) return fmtScore(idea.primary.mean);
  if (idea.statuses.some((s) => ACTIVE_STATUSES.has(s))) return "running";
  if (idea.statuses.length > 0 && idea.statuses.every((s) => FAILED_STATUSES.has(s))) {
    return "failed";
  }
  return DASH;
}

/** Seed noise under the score: identical seeds collapse to `◇×n`, never `± 0`. */
export function ideaSub(idea: IdeaRow): string {
  const p = idea.primary;
  if (!p) return "";
  if (idea.identical_seeds) return `◇×${p.n}`;
  if (p.n > 1) return `± ${fmtScore(p.std)}`;
  return "1 seed";
}

function SeedMark({ status, agent }: { status: RunStatus; agent: boolean }) {
  if (FAILED_STATUSES.has(status)) {
    return (
      <svg width="12" height="12" viewBox="-6 -6 12 12" data-seed="failed" aria-hidden="true">
        <path d="M-4,-4L4,4M4,-4L-4,4" stroke="var(--fail)" strokeWidth={1.8} />
      </svg>
    );
  }
  if (ACTIVE_STATUSES.has(status)) {
    return (
      <svg width="12" height="12" viewBox="-6 -6 12 12" data-seed="running" aria-hidden="true">
        <circle r={4.2} fill="none" stroke="var(--ink)" strokeWidth={1.4} strokeDasharray="2 2" />
      </svg>
    );
  }
  return (
    <svg width="12" height="12" viewBox="-6 -6 12 12" data-seed="ok" aria-hidden="true">
      <circle r={4.6} fill={agent ? "var(--agent)" : "var(--human)"} />
    </svg>
  );
}

function IntervalStrip({ idea, domain }: { idea: IdeaRow; domain: [number, number] }) {
  const x = scaleLinear().domain(domain).range([4, STRIP_W - 4]);
  const mid = STRIP_H / 2;
  const band = idea.best_band;
  const iv = idea.test_interval;
  return (
    <svg className="iv" viewBox={`0 0 ${STRIP_W} ${STRIP_H}`} preserveAspectRatio="none">
      {iv ? <title>{`95% CI ${fmtInterval(iv.lo, iv.hi)}`}</title> : null}
      {band ? (
        <rect
          x={x(band.lo)}
          y={0}
          width={Math.max(0, x(band.hi) - x(band.lo))}
          height={STRIP_H}
          fill="var(--best-wash)"
          stroke="var(--best-edge)"
        />
      ) : null}
      {iv ? (
        <g stroke="var(--ink-2)">
          <line x1={x(iv.lo)} x2={x(iv.hi)} y1={mid} y2={mid} />
          <line x1={x(iv.lo)} x2={x(iv.lo)} y1={mid - 5} y2={mid + 5} />
          <line x1={x(iv.hi)} x2={x(iv.hi)} y1={mid - 5} y2={mid + 5} />
        </g>
      ) : null}
      {idea.primary ? (
        <rect x={x(idea.primary.mean) - 3.5} y={mid - 3.5} width={7} height={7} fill="var(--ink)" />
      ) : null}
    </svg>
  );
}

function Axis({ domain }: { domain: [number, number] }) {
  const x = scaleLinear().domain(domain).range([4, STRIP_W - 4]);
  return (
    <div className="idea idea-axis">
      <span />
      <span />
      <svg viewBox={`0 0 ${STRIP_W} 24`}>
        {x.ticks(4).map((t) => (
          <text key={t} x={x(t)} y={16} textAnchor="middle">
            {t.toFixed(2)}
          </text>
        ))}
      </svg>
      <span />
    </div>
  );
}

export function IdeaList({ ideas }: { ideas: IdeaRow[] }) {
  if (ideas.length === 0) return <p className="small">no ideas in this window</p>;
  const domain = ideaDomain(ideas);
  return (
    <div>
      <ul className="ideas">
        {ideas.map((idea) => {
          const agent = isAgent(idea.created_by);
          return (
            <li key={idea.group_id} className={idea.primary ? "idea" : "idea dim"}>
              <span className="mks">
                {idea.statuses.map((status, i) => (
                  <SeedMark key={`${i}-${status}`} status={status} agent={agent} />
                ))}
              </span>
              <div>
                <div className="nm">
                  {idea.task ? (
                    <AppLink href={hrefs.task(idea.project, idea.task)}>{idea.label}</AppLink>
                  ) : (
                    idea.label
                  )}
                </div>
                <div className="meta">{`${idea.created_by}, ${fmtClock(idea.created_at)}`}</div>
              </div>
              {domain ? <IntervalStrip idea={idea} domain={domain} /> : <span />}
              <div className="sc">
                {ideaScore(idea)}
                <small title={idea.identical_seeds ? "all seeds gave the same score" : undefined}>
                  {ideaSub(idea)}
                </small>
              </div>
            </li>
          );
        })}
      </ul>
      {domain ? <Axis domain={domain} /> : null}
    </div>
  );
}
