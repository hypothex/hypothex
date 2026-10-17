import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { useNotify } from "../../api/queries";
import { PanelSection } from "../../chrome/PanelSection";
import { AppLink, hrefs } from "../components/links";
import { useIntent } from "./intent";
import { digestSchedule, noticeGlyph } from "./model";
export function Notifications() {
  const query = useNotify({ enabled: true }); const client = useQueryClient(); const [result, setResult] = useState<string | null>(null);
  const action = useIntent((channel: "slack" | "email", opts) => api.notifyTest(channel, opts), (data) => { setResult(data.ok ? "Test delivered" : `Delivery failed: ${data.error_class ?? "unknown error"}`); void client.invalidateQueries({ queryKey: ["notify"] }); });
  const data = query.data;
  return <PanelSection title="Notifications" grid="wide"><div className="phase3-section">
    {query.isPending ? <p role="status">Loading notifications…</p> : query.error ? <p role="alert">{query.error.message}</p> : data ? <>
      <p>Notification rules and secrets are configured with the CLI or config.yaml.</p>
      {(["slack", "email"] as const).map((channel) => { const c = data.channels[channel]; return <div key={channel}><h3>{channel === "slack" ? "Slack" : "Email"}</h3><p>{c.configured ? "Configured" : "Not configured"} · {c.env ?? "No environment variable"} · {c.set ? "Set" : "Unset"}</p>{channel === "email" ? <p>{data.channels.email.host} · {(data.channels.email.to ?? []).join(", ")}</p> : null}<button className="btn" disabled={!c.configured || !c.set || action.pending || query.isFetching} onClick={() => { setResult(null); void action.run(channel); }}>Test {channel === "slack" ? "Slack" : "email"}</button></div>; })}
      <h3>Project opt-in</h3><p>Default: {data.default ? `${data.default.events.join(", ") || "No run events"} · ${data.default.channels.join(", ")}` : "Off"}</p>
      <table aria-label="Notification rules"><thead><tr><th>Project</th><th>Events</th><th>Channels</th><th>Minimum seconds</th><th>Fold sweeps</th></tr></thead><tbody>{Object.entries(data.projects).map(([project, rule]) => <tr key={project}><td>{project}</td><td>{rule.events.join(", ") || "No run events"}</td><td>{rule.channels.join(", ")}</td><td>{rule.min_seconds}</td><td>{rule.fold_sweeps ? "Yes" : "No"}</td></tr>)}</tbody></table>
      <h3>Weekly digest</h3><p>{digestSchedule(data.digest)} · Save to notebook: {data.digest.save_to_notebook ? "Yes" : "No"}</p>
      <h3>Recent sends</h3>{!data.recent.length ? <p>No recent sends</p> : <div className="phase3-scroll"><table aria-label="Recent sends"><thead><tr><th>At</th><th>Run</th><th>Channel</th><th>State</th><th>Attempts</th><th>Error class</th></tr></thead><tbody>{data.recent.map((entry) => <tr key={`${entry.id}:${entry.channel}`}><td>{entry.sent_at ?? entry.created_at}</td><td>{entry.notice.run_id ? <AppLink href={hrefs.run(entry.notice.run_id)}>{entry.notice.run_id}</AppLink> : entry.notice.kind}</td><td>{entry.channel}</td><td>{noticeGlyph(entry.status)} {entry.status}</td><td>{entry.attempts}</td><td>{entry.last_error ?? "—"}</td></tr>)}</tbody></table></div>}
    </> : null}
    {action.error ? <p role="alert">{action.error.message}</p> : null}{result ? <p role="status">{result}</p> : null}
  </div></PanelSection>;
}
