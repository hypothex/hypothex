/** Run Examples tab: pick another config to compare example by example on the Examples page. */
import { fmtScoreUnit } from "../pages/components/format";
import { AppLink, hrefs } from "../pages/components/links";
import { type RunContext, exampleTargets } from "./runContext";

export function ExamplesTab({ ctx }: { ctx: RunContext }) {
  const data = ctx.taskRuns;
  if (!ctx.record.task || !data) {
    return (
      <div className="rmain">
        <p className="muted">Examples compare runs of one task; this run has no task.</p>
      </div>
    );
  }
  const others = exampleTargets(data, ctx.runId);
  return (
    <div className="rmain">
      <section aria-label="Compare examples">
        <h3>Compare examples with</h3>
        {others.length === 0 ? (
          <p className="muted">No other scored config in this task</p>
        ) : (
          <table className="t">
            <thead>
              <tr>
                <th aria-label="Colour" />
                <th>Config</th>
                <th className="num">{data.primary}</th>
                <th aria-label="Open" />
              </tr>
            </thead>
            <tbody>
              {others.map((o) => (
                <tr key={o.runId} aria-label={o.name}>
                  <td>
                    <span className="sw" style={{ background: o.color }} />
                  </td>
                  <td>{o.name}</td>
                  <td className="num">{fmtScoreUnit(o.primary, data.unit)}</td>
                  <td>
                    <AppLink className="btn sm" href={hrefs.examples(o.runId, ctx.runId)}>
                      Open
                    </AppLink>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
