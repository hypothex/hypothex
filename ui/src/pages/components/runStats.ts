/** The run page's stat strip: the few numbers that matter, tooltips for the rest. */
import { valueFormatter } from "../../charts/valueFormat";
import { fmtCount, fmtDuration, fmtInterval, fmtScore, fmtUsd, runSeconds } from "./format";
import { costNote } from "./remote";
import { type PrimaryRef, scoreFor } from "./ScoresList";
import type { StatItem } from "./StatStrip";
import type { LeaderboardRow, RunDetail } from "./types";

export function runStats(
  detail: RunDetail,
  primary: PrimaryRef | null,
  row: LeaderboardRow | null,
  now: number = Date.now(),
): StatItem[] {
  const out: StatItem[] = [];
  const record = detail.record;
  if (primary) {
    const value = scoreFor(detail.scores, `${primary.metric}@${primary.version}/${primary.key}`);
    if (value !== null) {
      const label = `${primary.metric} ${primary.version}${primary.key === "value" ? "" : `/${primary.key}`}`;
      const unit = primary.unit ?? "";
      if (unit || primary.valueFormat) {
        // `$` leads the number; other units sit beside it in the strip
        const f = valueFormatter({ unit, value_format: primary.valueFormat }, [value]);
        const prefix = unit === "$" || unit === "£" || unit === "€";
        out.push({
          label,
          value: prefix ? f.value(value) : f.num(value),
          unit: prefix ? null : unit || null,
          tooltip: "this run's primary score",
        });
      } else {
        out.push({ label, value: fmtScore(value), tooltip: "this run's primary score" });
      }
    }
    if (primary.interval) {
      const iv = primary.interval;
      out.push({
        label: "95% CI",
        value: fmtInterval(iv.lo, iv.hi),
        tooltip: `test-set interval of the seed group (${iv.method}, n = ${iv.n})`,
      });
    }
  }
  if (row) {
    out.push({
      label: "seeds",
      value: row.identical_seeds ? `◇×${row.n}` : String(row.n),
      tooltip: row.identical_seeds ? "every seed gave the same score" : "runs in this seed group",
    });
  }
  const seconds = runSeconds(record, now);
  if (seconds !== null) out.push({ label: "wall", value: fmtDuration(seconds) });
  const usage = record.usage;
  const cost = record.cost ?? null;
  if (usage) {
    out.push({ label: "tokens in", value: fmtCount(usage.tokens_in) });
    out.push({ label: "tokens out", value: fmtCount(usage.tokens_out) });
    if (!cost) out.push({ label: "cost", value: fmtUsd(usage.usd), tooltip: `${usage.calls} calls` });
  }
  // spec 8A.7: GPU hours × rate + API dollars, set when the run ends
  if (cost) out.push({ label: "cost", value: fmtUsd(cost.total_usd), tooltip: costNote(cost) });
  if (record.exit_code !== null && record.exit_code !== 0) {
    out.push({ label: "exit", value: String(record.exit_code) });
  }
  return out;
}
