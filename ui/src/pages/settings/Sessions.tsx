import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { auth } from "../../api/auth";
import type { Principal } from "../../api/models";
import { useSessions } from "../../api/queries";
import { PanelSection } from "../../chrome/PanelSection";
import { useIntent } from "./intent";
import { clientLabel, lastSeen, sessionState } from "./model";
export function Sessions({ principal }: { principal: Principal }) {
  const query = useSessions(principal.scope === "admin" ? undefined : principal.user ?? undefined, { enabled: principal.auth === "on" });
  const client = useQueryClient();
  const action = useIntent((id: string, opts) => api.revokeSession(id, opts), (_, id) => {
    if (id === principal.session_id) auth.lock(auth.snapshot().generation);
    else void client.invalidateQueries({ queryKey: ["auth", "sessions"] });
  });
  return <PanelSection title="Sessions" grid="wide"><div className="phase3-section">
    {query.isPending ? <p role="status">Loading sessions…</p> : query.error ? <p role="alert">{query.error.message}</p> : !query.data?.length ? <p>No sessions</p> : <div className="phase3-scroll"><table aria-label="Sessions"><thead><tr>{["Device", "User", "Client", "Scope", "Last seen", "Expiry / state", "Action"].map((s) => <th key={s}>{s}</th>)}</tr></thead><tbody>{query.data.map((s) => <tr key={s.id}><td>{s.device}{s.id === principal.session_id ? " · current session" : ""}</td><td>{s.user}</td><td>{clientLabel(s.client)}</td><td>{s.scope}</td><td>{lastSeen(s.last_seen_at, Date.now())}</td><td>{sessionState(s, Date.now())} · {s.expires_at}</td><td><button className="btn" disabled={action.pending || sessionState(s, Date.now()) !== "active"} onClick={() => void action.run(s.id)}>Revoke {s.device}</button></td></tr>)}</tbody></table></div>}
    {action.error ? <p role="alert">{action.error.message}</p> : null}
  </div></PanelSection>;
}
