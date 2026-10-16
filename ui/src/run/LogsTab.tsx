/** Run Logs tab: stdout, stderr or the supervisor log, chosen by `?log=`. */
import { AppLink, hrefs } from "../pages/components/links";
import { LogView } from "../pages/components/LogView";
import { LOG_STREAMS, type RunContext } from "./runContext";

export function LogsTab({ ctx }: { ctx: RunContext }) {
  const stream = ctx.log ?? "stdout";
  return (
    <div className="rmain">
      <nav className="seg" aria-label="Log stream">
        {LOG_STREAMS.map((s) => (
          <AppLink
            key={s}
            className={s === stream ? "on" : undefined}
            aria-current={s === stream ? "true" : undefined}
            href={hrefs.run(ctx.runId, { tab: "logs", log: s })}
          >
            {s}
          </AppLink>
        ))}
      </nav>
      <LogView runId={ctx.runId} stream={stream} />
    </div>
  );
}
