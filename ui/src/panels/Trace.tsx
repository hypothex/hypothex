/**
 * Trace panel: the step list of one agent attempt, with the failing turn marked.
 */
import type { CSSProperties } from "react";
import type { TraceRow } from "../api/models";
import type { PanelResult } from "./index";

/** One trace step, as returned by the query engine (contract 1.6). */
export type TraceStep = TraceRow;

/** Width in px of the longest seconds bar. */
export const BAR_MAX = 56;

/** Format a token count: `250`, `1.2k`, `15k`, `2.50M`. */
export function kTok(v: number): string {
  if (v < 1000) return String(Math.round(v));
  if (v < 1e4) return `${(v / 1000).toFixed(1)}k`;
  if (v < 1e6) return `${Math.round(v / 1000)}k`;
  return `${(v / 1e6).toFixed(2)}M`;
}

/** Render a JSON value as one line, cut to `max` characters with an ellipsis. */
export function shortText(v: unknown, max = 120): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function fullText(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

const FAIL_WASH = "color-mix(in srgb, var(--fail) 8%, transparent)";

const S = {
  cap: { fontSize: 12.5, color: "var(--ink-3)", margin: "0 0 10px" },
  capFail: { color: "var(--fail)" },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13.5,
    fontVariantNumeric: "tabular-nums",
  },
  th: {
    textAlign: "left",
    fontWeight: 500,
    color: "var(--ink-3)",
    fontSize: 12.5,
    padding: "0 10px 8px 0",
    borderBottom: "1px solid var(--rule)",
    whiteSpace: "nowrap",
  },
  td: {
    padding: "7px 10px 7px 0",
    borderBottom: "1px solid var(--rule-2)",
    verticalAlign: "middle",
    whiteSpace: "nowrap",
  },
  n: { color: "var(--ink-3)", width: 34, paddingLeft: 8 },
  tool: { fontFamily: "var(--mono)", fontSize: 12.5, color: "var(--ink)" },
  args: {
    fontFamily: "var(--mono)",
    fontSize: 12,
    color: "var(--ink-2)",
    maxWidth: 0,
    width: "36%",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  res: {
    color: "var(--ink-2)",
    maxWidth: 0,
    width: "30%",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  r: { textAlign: "right" },
  msb: { display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end" },
  bar: { display: "block", height: 6, borderRadius: "0 3px 3px 0" },
  warn: { color: "var(--human)", fontWeight: 700, marginLeft: 4 },
  foot: { color: "var(--ink-3)", fontSize: 12.5, paddingTop: 10 },
  b: { color: "var(--ink)", fontWeight: 500 },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Trace panel. Reads `meta.run_id`, `meta.example_id` and `meta.failed_turn`. */
export function TracePanel({ result }: { result: PanelResult }) {
  const steps = result.rows as unknown as TraceStep[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  const failedTurn = typeof meta.failed_turn === "number" ? meta.failed_turn : null;
  const runId = typeof meta.run_id === "string" ? meta.run_id : null;
  const exampleId = typeof meta.example_id === "string" ? meta.example_id : null;
  if (steps.length === 0) return <p style={S.empty}>No trace</p>;

  const maxS = Math.max(0, ...steps.map((s) => s.seconds ?? 0));
  const sum = (key: "tokens_in" | "tokens_out" | "seconds") =>
    steps.reduce((acc, s) => acc + (s[key] ?? 0), 0);

  return (
    <div>
      <p style={S.cap}>
        {runId && <a href={`/r/${encodeURIComponent(runId)}`}>{runId}</a>}
        {exampleId && <span> · {exampleId}</span>}
        {failedTurn !== null && <span style={S.capFail}> · failed at turn {failedTurn}</span>}
      </p>
      <table style={S.table} aria-label="Trajectory">
        <thead>
          <tr>
            <th style={{ ...S.th, ...S.n }}>#</th>
            <th style={S.th}>tool</th>
            <th style={S.th}>args</th>
            <th style={S.th}>result</th>
            <th style={{ ...S.th, ...S.r }} title="tokens in">
              in
            </th>
            <th style={{ ...S.th, ...S.r }} title="tokens out">
              out
            </th>
            <th style={{ ...S.th, ...S.r }} title="seconds">
              s
            </th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => {
            const failed = s.turn === failedTurn;
            const warn = !failed && Boolean(s.error);
            const shown = s.error ?? s.result;
            const td: CSSProperties = failed ? { ...S.td, background: FAIL_WASH } : S.td;
            const bar = maxS > 0 ? Math.round(((s.seconds ?? 0) / maxS) * BAR_MAX) : 0;
            return (
              <tr
                key={s.turn}
                data-turn={s.turn}
                data-failed={failed ? "true" : "false"}
                data-warn={warn ? "true" : "false"}
                title={s.error ?? undefined}
              >
                <td
                  style={{
                    ...td,
                    ...S.n,
                    ...(failed
                      ? {
                          color: "var(--fail)",
                          fontWeight: 600,
                          boxShadow: "inset 3px 0 0 var(--fail)",
                        }
                      : {}),
                  }}
                >
                  {s.turn}
                  {warn && <span style={S.warn}>!</span>}
                </td>
                <td style={{ ...td, ...S.tool }}>{s.tool}</td>
                <td style={{ ...td, ...S.args }} title={fullText(s.args)}>
                  {shortText(s.args)}
                </td>
                <td
                  style={{
                    ...td,
                    ...S.res,
                    ...(failed ? { color: "var(--fail)", fontWeight: 600 } : {}),
                    ...(warn ? { color: "var(--ink)" } : {}),
                  }}
                  title={fullText(shown)}
                >
                  {shortText(shown)}
                </td>
                <td style={{ ...td, ...S.r }}>{s.tokens_in === null ? "" : kTok(s.tokens_in)}</td>
                <td style={{ ...td, ...S.r }}>{s.tokens_out === null ? "" : kTok(s.tokens_out)}</td>
                <td style={{ ...td, width: 132 }}>
                  <span style={S.msb}>
                    <i
                      data-testid="sbar"
                      style={{
                        ...S.bar,
                        width: bar,
                        background: failed ? "var(--fail)" : "var(--ink-3)",
                        opacity: failed ? 1 : 0.55,
                      }}
                    />
                    {s.seconds === null ? "" : s.seconds.toFixed(1)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td style={S.foot} />
            <td style={S.foot}>
              <b style={S.b} data-testid="turns">
                {steps.length}
              </b>{" "}
              turns
            </td>
            <td style={S.foot} />
            <td style={S.foot} />
            <td style={{ ...S.foot, ...S.r }}>
              <b style={S.b} data-testid="sum-in">
                {kTok(sum("tokens_in"))}
              </b>
            </td>
            <td style={{ ...S.foot, ...S.r }}>
              <b style={S.b} data-testid="sum-out">
                {kTok(sum("tokens_out"))}
              </b>
            </td>
            <td style={{ ...S.foot, ...S.r }}>
              <b style={S.b} data-testid="sum-s">
                {sum("seconds").toFixed(1)}
              </b>{" "}
              s
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export default TracePanel;
