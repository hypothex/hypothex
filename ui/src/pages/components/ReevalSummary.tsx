/** Shared task/run re-evaluation feedback; full reasons remain in the tooltip. */
import type { EvalReport } from "../../api/models";

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/**
 * What a re-evaluation did, in one line: `0 re-scored · 1 skipped: no predictions`.
 * Skip reasons are counted (`×N`) when there is more than one kind.
 */
export function reevalLine(report: EvalReport): string {
  const skipped = Object.values(report.skipped ?? {});
  const warnings = report.warnings ?? [];
  const out = [`${(report.evaluated ?? []).length} re-scored`];
  if (skipped.length > 0) {
    const reasons = new Map<string, number>();
    for (const why of skipped) reasons.set(why, (reasons.get(why) ?? 0) + 1);
    const many = reasons.size > 1;
    const text = [...reasons].map(([why, n]) => (many ? `${why} ×${n}` : why)).join(", ");
    out.push(`${skipped.length} skipped: ${text}`);
  }
  if (warnings.length > 0) out.push(plural(warnings.length, "warning", "warnings"));
  return out.join(" · ");
}

/** The skipped runs and the warnings of a re-evaluation, one per line, for the tooltip. */
export function reevalDetail(report: EvalReport): string | undefined {
  const lines = [
    ...Object.entries(report.skipped ?? {}).map(([id, why]) => `${id}: ${why}`),
    ...(report.warnings ?? []),
  ];
  return lines.length > 0 ? lines.join("\n") : undefined;
}

export function ReevalSummary({ report }: { report: EvalReport }) {
  return (
    <p className="small" role="status" aria-label="Re-evaluate" title={reevalDetail(report)}>
      {reevalLine(report)}
    </p>
  );
}
