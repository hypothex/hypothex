/** Overview panel: runs over time, one lane per launcher (agent vs human, spec 8.3.1). */
import { scaleLinear } from "d3-scale";
import { useElementWidth } from "../../charts/Scale";
import { fmtClock, fmtTime, isAgent, parseTime } from "./format";
import { hrefs, useNavigateHref } from "./links";
import { FAILED_STATUSES, type TimelineItem } from "./types";

/** Width used before layout is known (and in test DOMs). */
export const TIMELINE_FALLBACK_W = 1000;
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

/** Estimated width in px of `text` at `px` size (Geist averages ~0.56 em a glyph). */
export function textWidth(text: string, px = 12, bold = false): number {
  return Math.ceil(text.length * px * (bold ? 0.62 : 0.56));
}

/** A label that wants to sit centred over `x`; higher `priority` is placed first. */
export interface LabelCandidate {
  key: string;
  text: string;
  x: number;
  w: number;
  priority: number;
  /** Largest slide from `x` for this label; overrides the default. */
  maxShift?: number;
}

/** A placed label: centre `cx` and tier (0 above the lane, 1 below it). */
export interface PlacedLabel extends LabelCandidate {
  cx: number;
  tier: 0 | 1;
}

const LABEL_GAP = 8;

/**
 * Place lane labels so no two overlap.
 *
 * Labels go in priority order (ties: newest first). Each tries the tier above the lane,
 * then the tier below, at its own x or slid just clear of a neighbour, but never further
 * than `maxShift` px (default: half its width plus 12) from its marks and never outside
 * `[x0, x1]`. Labels with no free spot are returned in `dropped`.
 */
export function placeLabels(
  cands: LabelCandidate[],
  x0: number,
  x1: number,
  maxShift?: number,
): { placed: PlacedLabel[]; dropped: LabelCandidate[] } {
  const order = [...cands].sort((a, b) => b.priority - a.priority || b.x - a.x);
  const placed: PlacedLabel[] = [];
  const dropped: LabelCandidate[] = [];
  const free = (cx: number, w: number, tier: 0 | 1) =>
    placed.every(
      (p) => p.tier !== tier || cx + w / 2 + LABEL_GAP <= p.cx - p.w / 2 || cx - w / 2 >= p.cx + p.w / 2 + LABEL_GAP,
    );
  for (const c of order) {
    const lo = x0 + c.w / 2;
    const hi = x1 - c.w / 2;
    if (hi < lo) {
      dropped.push(c);
      continue;
    }
    const clamp = (v: number) => Math.min(hi, Math.max(lo, v));
    const limit = c.maxShift ?? maxShift ?? c.w / 2 + 12;
    let spot: PlacedLabel | null = null;
    for (const tier of [0, 1] as const) {
      const tries = [clamp(c.x)];
      for (const p of placed) {
        if (p.tier !== tier) continue;
        tries.push(p.cx - p.w / 2 - LABEL_GAP - c.w / 2, p.cx + p.w / 2 + LABEL_GAP + c.w / 2);
      }
      const ok = tries
        .filter((cx) => cx >= lo && cx <= hi && Math.abs(cx - c.x) <= Math.max(limit, Math.abs(clamp(c.x) - c.x)))
        .sort((a, b) => Math.abs(a - c.x) - Math.abs(b - c.x))
        .find((cx) => free(cx, c.w, tier));
      if (ok !== undefined) {
        spot = { ...c, cx: ok, tier };
        break;
      }
    }
    if (spot) placed.push(spot);
    else dropped.push(c);
  }
  return { placed, dropped };
}

/** One lane's labels after collision avoidance, plus a `+N` label for the dropped ones. */
export interface LaneLabels {
  placed: (PlacedLabel & { best: boolean })[];
  more: (PlacedLabel & { names: string[] }) | null;
}

/**
 * Label one lane: best clusters first, then running ones, then newest. Labels that do
 * not fit are replaced by one `+N` label (placed anywhere free in the lane) whose tooltip
 * names them.
 */
export function laneLabels(cs: Cluster[], xOf: (c: Cluster) => number, x0: number, x1: number): LaneLabels {
  const cands: LabelCandidate[] = [];
  cs.forEach((c, i) => {
    const text = clusterText(c);
    const running = c.items.some((it) => it.status === "running" || it.status === "queued");
    const cand = { key: String(i), text, x: xOf(c), w: textWidth(text, 12, c.best), priority: c.best ? 3 : running ? 2 : 1 };
    // interleaved runs of one idea split into clusters with the same text: label them once
    const twin = cands.find((o) => o.text === text && Math.abs(o.x - cand.x) < Math.max(cand.w, 60));
    if (twin) {
      twin.x = (twin.x + cand.x) / 2;
      twin.priority = Math.max(twin.priority, cand.priority);
    } else cands.push(cand);
  });
  const first = placeLabels(cands, x0, x1);
  if (first.dropped.length === 0) {
    return { placed: first.placed.map((p) => ({ ...p, best: cs[Number(p.key)]?.best ?? false })), more: null };
  }
  const text = `+${first.dropped.length}`;
  const mx = first.dropped.reduce((a, d) => a + d.x, 0) / first.dropped.length;
  const moreCand = { key: "more", text, x: mx, w: textWidth(text), priority: -1, maxShift: Number.POSITIVE_INFINITY };
  const second = placeLabels([...cands, moreCand], x0, x1);
  const placed = second.placed
    .filter((p) => p.key !== "more")
    .map((p) => ({ ...p, best: cs[Number(p.key)]?.best ?? false }));
  const hit = second.placed.find((p) => p.key === "more");
  const names = first.dropped.map((d) => d.text);
  return { placed, more: hit ? { ...hit, names } : null };
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

/** y offset of each label tier from the lane line: above, below. */
const TIER_DY = [-12, 20] as const;

export function RunTimeline({ items }: { items: TimelineItem[] }) {
  const navigate = useNavigateHref();
  const [ref, W] = useElementWidth<HTMLDivElement>(TIMELINE_FALLBACK_W);
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
  const maxTicks = Math.max(2, Math.min(6, Math.floor((W - LEFT) / 70)));
  return (
    <div className="timeline" ref={ref}>
      <svg width={W} height={height} aria-label="Runs by launcher over time">
        {timeTicks(lo, hi, maxTicks).map((t) => (
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
          const labels = laneLabels(
            clusters(row.items),
            (c) => c.items.reduce((sum, i) => sum + x(at(i)), 0) / c.items.length,
            LEFT,
            W,
          );
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
              {labels.placed.map((p) => (
                <text
                  key={p.key}
                  className={p.best ? "cl best" : "cl"}
                  data-tier={p.tier}
                  x={p.cx}
                  y={y + TIER_DY[p.tier]}
                  textAnchor="middle"
                >
                  {p.text}
                </text>
              ))}
              {labels.more ? (
                <text
                  className="cl more"
                  data-tier={labels.more.tier}
                  x={labels.more.cx}
                  y={y + TIER_DY[labels.more.tier]}
                  textAnchor="middle"
                >
                  <title>{labels.more.names.join("\n")}</title>
                  {labels.more.text}
                </text>
              ) : null}
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
