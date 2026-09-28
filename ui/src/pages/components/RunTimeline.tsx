/** Overview panel: runs over time, one lane per launcher (agent vs human, spec 8.3.1). */
import { scaleLinear } from "d3-scale";
import { fmtClock, fmtTime, isAgent, parseTime } from "./format";
import { hrefs, useNavigateHref } from "./links";
import { FAILED_STATUSES, type TimelineItem } from "./types";

const W = 1000;
const LEFT = 190;
const PAD = 14;
const TOP = 26;
const ROW_H = 64;
const AXIS_H = 30;
const STEPS_MIN = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440];

export interface TimelineRow {
  launcher: string;
  agent: boolean;
  items: TimelineItem[];
  failed: number;
}

const at = (item: TimelineItem): number => parseTime(item.created_at);

/** Group items by launcher; agent lanes first, then by name; items oldest first. */
export function timelineRows(items: TimelineItem[]): TimelineRow[] {
  const byLauncher = new Map<string, TimelineItem[]>();
  for (const item of items) {
    const list = byLauncher.get(item.created_by) ?? [];
    list.push(item);
    byLauncher.set(item.created_by, list);
  }
  return [...byLauncher.entries()]
    .map(([launcher, list]) => ({
      launcher,
      agent: isAgent(launcher),
      items: [...list].sort((a, b) => at(a) - at(b)),
      failed: list.filter((i) => FAILED_STATUSES.has(i.status)).length,
    }))
    .sort((a, b) => Number(b.agent) - Number(a.agent) || a.launcher.localeCompare(b.launcher));
}

export type MarkKind = "failed" | "archived" | "best" | "running" | "agent" | "human";

/** How to draw one run: failure beats archived beats best beats running. */
export function markKind(item: TimelineItem): MarkKind {
  if (FAILED_STATUSES.has(item.status)) return "failed";
  if (item.archived) return "archived";
  if (item.is_best) return "best";
  if (item.status === "running" || item.status === "queued") return "running";
  return isAgent(item.created_by) ? "agent" : "human";
}

export interface Cluster {
  label: string;
  items: TimelineItem[];
  best: boolean;
}

/** Merge neighbouring runs with the same label so each idea is labelled once. */
export function clusters(items: TimelineItem[]): Cluster[] {
  const out: Cluster[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (last && last.label === item.label) {
      last.items.push(item);
      last.best = last.best || item.is_best;
    } else {
      out.push({ label: item.label, items: [item], best: item.is_best });
    }
  }
  return out;
}

export function clusterText(c: Cluster): string {
  return c.best ? `${c.label}, best` : c.label;
}

/** Tick times (ms) on whole minutes or hours, at most `maxTicks` of them. */
export function timeTicks(lo: number, hi: number, maxTicks = 6): number[] {
  const spanMin = (hi - lo) / 60_000;
  const step = (STEPS_MIN.find((s) => spanMin / s <= maxTicks) ?? 1440) * 60_000;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t);
  return out;
}

function Mark({ kind, agent }: { kind: MarkKind; agent: boolean }) {
  const color = agent ? "var(--agent)" : "var(--human)";
  switch (kind) {
    case "failed":
      return <path d="M-4,-4L4,4M4,-4L-4,4" stroke="var(--fail)" strokeWidth={1.8} />;
    case "archived":
      return <circle r={4.2} fill="none" stroke={color} strokeWidth={1.4} />;
    case "best":
      return <circle r={4.6} fill="var(--best)" />;
    case "running":
      return <circle r={4.2} fill="none" stroke="var(--ink)" strokeWidth={1.4} strokeDasharray="2 2" />;
    case "agent":
      return <circle r={4.6} fill={color} />;
    case "human":
      return <rect x={-4.2} y={-4.2} width={8.4} height={8.4} fill={color} />;
  }
}

function markName(item: TimelineItem): string {
  return `${item.label}, ${item.status}${item.is_best ? ", best" : ""}, ${fmtClock(item.created_at)}`;
}

function Key() {
  const entries: [MarkKind, boolean, string][] = [
    ["agent", true, "agent"],
    ["human", false, "human"],
    ["best", true, "current best"],
    ["failed", true, "failed"],
    ["archived", true, "archived"],
  ];
  return (
    <div className="key">
      {entries.map(([kind, agent, text]) => (
        <span key={text}>
          <svg width="12" height="12" viewBox="-6 -6 12 12" aria-hidden="true">
            <Mark kind={kind} agent={agent} />
          </svg>
          {text}
        </span>
      ))}
    </div>
  );
}

export function RunTimeline({ items }: { items: TimelineItem[] }) {
  const navigate = useNavigateHref();
  if (items.length === 0) return <p className="small">no runs in this window</p>;
  const rows = timelineRows(items);
  const times = items.map(at);
  let lo = Math.min(...times);
  let hi = Math.max(...times);
  if (hi - lo < 60_000) {
    lo -= 30_000;
    hi += 30_000;
  }
  const x = scaleLinear().domain([lo, hi]).range([LEFT + PAD, W - PAD]);
  const height = TOP + rows.length * ROW_H + AXIS_H;
  const axisY = height - AXIS_H;
  return (
    <div className="timeline">
      <svg viewBox={`0 0 ${W} ${height}`} aria-label="Runs by launcher over time">
        {timeTicks(lo, hi).map((t) => (
          <g key={t} transform={`translate(${x(t)},0)`}>
            <line className="grid" y1={TOP - 16} y2={axisY} />
            <text className="tick" y={axisY + 18} textAnchor="middle">
              {fmtClock(new Date(t).toISOString())}
            </text>
          </g>
        ))}
        <line className="axis" x1={LEFT + PAD} x2={W - PAD} y1={axisY} y2={axisY} />
        {rows.map((row, ri) => {
          const y = TOP + ri * ROW_H + ROW_H / 2;
          return (
            <g key={row.launcher} data-row={row.launcher}>
              <text className="ln" x={14} y={y - 2}>
                {row.launcher}
              </text>
              <g transform={`translate(4,${y - 6})`}>
                <Mark kind={row.agent ? "agent" : "human"} agent={row.agent} />
              </g>
              <text className="lc" x={14} y={y + 14}>
                {`${row.items.length} ${row.items.length === 1 ? "run" : "runs"}${row.failed ? `, ${row.failed} failed` : ""}`}
              </text>
              <line className="lane" x1={LEFT + PAD} x2={W - PAD} y1={y} y2={y} />
              {clusters(row.items).map((c) => {
                const cx = c.items.reduce((sum, i) => sum + x(at(i)), 0) / c.items.length;
                return (
                  <text
                    key={`${c.label}-${c.items[0]?.run_id ?? ""}`}
                    className={c.best ? "cl best" : "cl"}
                    x={cx}
                    y={y - 12}
                    textAnchor="middle"
                  >
                    {clusterText(c)}
                  </text>
                );
              })}
              {row.items.map((item) => {
                const kind = markKind(item);
                const href = hrefs.run(item.run_id);
                return (
                  <g
                    key={item.run_id}
                    className="mark"
                    data-mark={kind}
                    role="link"
                    tabIndex={0}
                    aria-label={markName(item)}
                    transform={`translate(${x(at(item))},${y})`}
                    onClick={() => navigate(href)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") navigate(href);
                    }}
                  >
                    <title>{`${item.label} · ${item.status} · ${fmtTime(item.created_at)} · ${item.run_id}`}</title>
                    <Mark kind={kind} agent={row.agent} />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <Key />
    </div>
  );
}
