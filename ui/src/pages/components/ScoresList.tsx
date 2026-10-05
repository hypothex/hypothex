/** Run panel: scores by metric version (spec 8.3.3). */
import { fmtClock, fmtInterval, fmtScore, shortHash } from "./format";
import type { Leaderboard, LeaderboardRow, NoiseInterval, ScoreRecord } from "./types";

/** The newest score per (metric, version, key), sorted by metric, version, key. */
export function latestScores(scores: ScoreRecord[]): ScoreRecord[] {
  const newest = new Map<string, ScoreRecord>();
  for (const s of scores) {
    const key = `${s.metric}\u0000${s.version}\u0000${s.key}`;
    const current = newest.get(key);
    if (!current || s.created_at > current.created_at) newest.set(key, s);
  }
  return [...newest.values()].sort(
    (a, b) =>
      a.metric.localeCompare(b.metric) ||
      a.version.localeCompare(b.version) ||
      a.key.localeCompare(b.key),
  );
}

/** `accuracy v1`, or `accuracy v1/top5` for a non-`value` key. */
export function scoreLabel(s: ScoreRecord): string {
  return `${s.metric} ${s.version}${s.key === "value" ? "" : `/${s.key}`}`;
}

/**
 * A current score for `name`, `name@version`, or `name@version/key`.
 * Select the requested/preferred key before validating it: a failed value must not
 * fall back to a different field. A same-version wildcard error invalidates values
 * recorded at or before that attempt, including partial values from that attempt.
 * Timestamped history remains available through `latestScores` and `ScoresList`.
 */
export function scoreFor(scores: ScoreRecord[], ref: string): number | null {
  const [head = "", key] = ref.split("/");
  const [name = "", version] = head.split("@");
  const candidates = latestScores(scores).filter(
    (s) => s.metric === name && (version === undefined || s.version === version),
  );
  const pick = candidates.find((s) => s.key === (key ?? "value"))
    ?? (key ? undefined : candidates.find((s) => s.key !== "*"));
  if (!pick || pick.error !== null || pick.value === null || !Number.isFinite(pick.value)) return null;
  const failed = candidates.some((s) => s.version === pick.version && s.key === "*"
    && s.error !== null && s.created_at >= pick.created_at);
  return failed ? null : pick.value;
}

export interface PrimaryRef {
  metric: string;
  version: string;
  key: string;
  interval: NoiseInterval | null;
  /** Display unit of the primary metric (`board.unit`), `""` when none. */
  unit?: string;
  /** Format hint (`board.value_format`). */
  valueFormat?: string;
}

/** The task's primary metric at its current version, with the run group's test interval. */
export function primaryRef(board: Leaderboard | null, row: LeaderboardRow | null): PrimaryRef | null {
  if (!board) return null;
  const [metric = board.primary, key = "value"] = board.primary.split("/");
  const version = board.metric_versions[metric];
  if (!version) return null;
  return {
    metric,
    version,
    key,
    interval: row?.test_interval ?? null,
    unit: board.unit ?? "",
    valueFormat: board.value_format,
  };
}

export interface ScoresListProps {
  scores: ScoreRecord[];
  metricNames: string[];
  primary: PrimaryRef | null;
}

export function ScoresList({ scores, metricNames, primary }: ScoresListProps) {
  const rows = latestScores(scores);
  const logged = metricNames.slice(0, 20).map((name) => name.length > 48 ? `${name.slice(0, 47)}…` : name);
  const remaining = metricNames.length > 20 ? ` +${metricNames.length - 20}` : "";
  return (
    <div>
      {rows.length === 0 ? (
        <p className="small">no scores</p>
      ) : (
        <table className="scores">
          <tbody>
            {rows.map((s) => {
              const isPrimary =
                primary !== null &&
                s.metric === primary.metric &&
                s.version === primary.version &&
                s.key === primary.key;
              const iv = isPrimary ? primary.interval : null;
              return (
                <tr key={`${s.metric}@${s.version}/${s.key}`}>
                  <td>
                    {scoreLabel(s)}
                    <small>
                      {s.source_hash
                        ? `${fmtClock(s.created_at)} · ${shortHash(s.source_hash)}`
                        : fmtClock(s.created_at)}
                    </small>
                  </td>
                  <td className="v">
                    {s.error ? (
                      <span className="err" title={s.error}>
                        error
                      </span>
                    ) : (
                      <span>{fmtScore(s.value)}</span>
                    )}
                    {iv ? (
                      <small title={`test-set 95% interval (${iv.method}, n = ${iv.n})`}>
                        {fmtInterval(iv.lo, iv.hi)}
                      </small>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {metricNames.length > 0 ? (
        <p className="small" style={{ overflowWrap: "anywhere" }} title={metricNames.join(", ")}>
          {`logged: ${logged.join(", ")}${remaining}`}
        </p>
      ) : null}
    </div>
  );
}
